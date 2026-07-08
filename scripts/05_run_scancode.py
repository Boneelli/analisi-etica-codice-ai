"""
05_run_scancode.py

Rileva, per ogni PR del subset, usando SOLO i file scaricati da
02_fetch_files.py (niente repo clonato):
  1. Conflitti di licenza: confronta la licenza dichiarata dal repository
     (colonna 'license' della tabella 'repository' nei metadati AIDev,
     confermata presente - disponibile come 'repo_license' dopo il join
     fatto in 01_build_subset.py) con le licenze rilevate da ScanCode nei
     singoli file toccati dalla PR. Un conflitto e' tipicamente:
     - file con licenza diversa/incompatibile rispetto al repo (es. codice
       copiato da una libreria GPL in un repo MIT)
     - presenza di piu' licenze tra loro incompatibili nello stesso file/PR
  2. Copyright Stripping: confronta le dichiarazioni di copyright presenti
     nella cartella data/files/<pr_id>/before (file completi pre-PR,
     scaricati via raw URL al commit padre) con quelle in
     data/files/<pr_id>/after (post-PR). Se un blocco di copyright/
     attribuzione presente prima scompare dopo, senza che il codice
     sottostante sia stato riscritto, e' un caso di "copyright stripping"
     potenziale.

Installazione:
    pip install scancode-toolkit --break-system-packages
    # ScanCode ha molte dipendenze native; in alternativa usare il
    # docker image ufficiale: docker pull nexb/scancode-toolkit

Uso CLI equivalente (utile per debug):
    scancode --license --copyright --json-pp report.json <path>

Output: results/scancode_raw/<pr_id>.json  (output grezzo per audit)
        results/license_conflicts.csv
        results/copyright_stripping.csv
"""

import subprocess
import json
import pandas as pd
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
SUBSET_DIR = RESULTS_DIR / "subset"
IP_RIGHTS_DIR = RESULTS_DIR / "ip_rights"
SCANCODE_RAW_DIR = IP_RIGHTS_DIR / "scancode_raw"
SCANCODE_RAW_DIR.mkdir(exist_ok=True, parents=True)

# Tabella di compatibilita' licenze (coppie considerate un VERO conflitto).
# ATTENZIONE METODOLOGICA: questa tabella e' ancora semplificata e va
# validata con una fonte SPDX riconosciuta prima del paper finale (es.
# la matrice di compatibilita' di https://github.com/david-a-wheeler/spdx-compat
# o equivalenti). In particolare, la compatibilita' tra licenze e'
# DIREZIONALE e dipende dal contesto (una permissiva puo' stare dentro una
# copyleft, ma non viceversa): una tabella a coppie simmetriche come questa
# e' un'approssimazione.
#
# NOTA: le coppie tipo "agpl-3.0 + mit" e "agpl-3.0 + apache-2.0" sono state
# RIMOSSE da questa lista perche' NON sono veri conflitti: MIT e Apache-2.0
# sono licenze permissive e possono legittimamente essere incluse in un
# progetto AGPL/GPL. Includerle generava falsi positivi massicci (es. tutte
# le dipendenze MIT/Apache elencate in un package-lock.json dentro un repo
# AGPL venivano contate come "conflitti").
INCOMPATIBLE_PAIRS = {
    # Esempi di conflitti piu' plausibili (copyleft forte incompatibile tra loro,
    # o copyleft dentro un contesto che non lo consente). DA VALIDARE.
    frozenset({"gpl-2.0", "gpl-3.0"}),        # GPL-2.0-only e GPL-3.0 sono notoriamente incompatibili tra loro
    frozenset({"gpl-3.0", "apache-2.0"}),     # compatibilita' direzionale problematica in certi versi (semplificazione)
}

# File da ESCLUDERE dal rilevamento conflitti di licenza: sono file di lock /
# metadati auto-generati che elencano le licenze di TUTTE le dipendenze
# transitive del progetto. Non sono codice scritto dall'agente e le licenze
# che contengono sono quelle delle librerie di terze parti, non del progetto:
# includerli genera falsi positivi massicci (es. 41 "conflitti" tutti da un
# singolo package-lock.json). Il match e' sul nome file (case-insensitive),
# tenendo conto che safe_path() ha appiattito il path con "__".
LICENSE_SCAN_EXCLUDE_BASENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
    "cargo.lock", "poetry.lock", "pdm.lock", "gemfile.lock", "composer.lock",
    "go.sum", "packages.lock.json", "flake.lock",
}


def is_excluded_from_license_scan(file_path: str) -> bool:
    """
    True se il file va escluso dal rilevamento conflitti di licenza perche'
    e' un lock file / metadati auto-generati. Il file_path qui e' quello
    "appiattito" da safe_path() (separatori '/' -> '__') E con un hash
    inserito prima dell'estensione (es. "package-lock.json" diventa
    "..._package-lock__99acb439.json"). Quindi NON si puo' usare endswith()
    sul basename intero: si estrae la parte "stem" (nome senza estensione),
    si rimuove l'eventuale suffisso hash "__xxxxxxxx", e si confronta il
    nome-base risultante con i pattern noti.
    """
    lower = file_path.lower()

    # Prendi l'ultimo segmento dopo l'ultimo separatore appiattito "__" o "/"
    # e ricostruisci il nome file "logico" (senza il percorso appiattito).
    # Poi confronta contro i basename noti, ignorando l'hash inserito da
    # safe_path tra stem ed estensione.
    for basename in LICENSE_SCAN_EXCLUDE_BASENAMES:
        stem, _, ext = basename.rpartition(".")  # es. "package-lock", "json"
        if stem and ext:
            # cerca "package-lock" ... ".json" con qualcosa (l'hash) in mezzo,
            # oppure il nome esatto senza hash
            if (f"{stem}__" in lower and lower.endswith(f".{ext}")) or lower.endswith(f"{stem}.{ext}"):
                return True
        else:
            # basename senza estensione (raro), match diretto
            if lower.endswith(basename):
                return True
    return False


def run_scancode(path: Path, pr_id) -> dict | None:
    out_path = SCANCODE_RAW_DIR / f"{pr_id}.json"

    # RIUSO DEI RISULTATI GIA' PRODOTTI: la scansione ScanCode e' lentissima
    # (l'operazione piu' lenta di tutta la pipeline). Se il JSON per questa PR
    # esiste gia' ed e' leggibile - ad esempio da una run precedente che si e'
    # interrotta a meta' per un errore nella fase di ANALISI (non di scansione)
    # - lo si riusa invece di riscansionare da zero. Questo rende lo script
    # ri-eseguibile senza rifare l'ora di scansione gia' completata.
    if out_path.exists() and out_path.stat().st_size > 0:
        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # JSON corrotto/incompleto (es. scansione interrotta a meta' su
            # questa specifica PR): lo si rigenera riscansionando.
            log.info(f"JSON esistente per PR {pr_id} corrotto, riscansiono.")

    cmd = [
        "scancode",
        "--license",
        "--copyright",
        "--info",
        "--json-pp", str(out_path),
        "--processes", "2",
        str(path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except subprocess.CalledProcessError as e:
        log.warning(f"ScanCode fallito su PR {pr_id}: {e.stderr.decode(errors='ignore')[:300]}")
        return None
    except subprocess.TimeoutExpired:
        log.warning(f"ScanCode timeout su PR {pr_id}")
        return None

    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    return None


def detect_license_conflicts(scan_result: dict, repo_declared_license) -> list[dict]:
    conflicts = []

    # La licenza dichiarata puo' arrivare come stringa (es. "MIT"), ma anche
    # come NaN (float) quando la colonna repository.license e' vuota per quel
    # repo, o come None. pandas rappresenta i valori mancanti con NaN, che e'
    # un float e non ha .lower(): senza questo controllo il codice crashava
    # con "'float' object has no attribute 'lower'". Trattiamo qualsiasi
    # valore non-stringa (o la stringa speciale "NOASSERTION", che GitHub usa
    # quando non riesce a determinare la licenza) come "licenza non dichiarata":
    # in quel caso non ha senso cercare conflitti, si salta.
    if not isinstance(repo_declared_license, str):
        repo_license_key = ""
    else:
        repo_license_key = repo_declared_license.lower().strip()
        if repo_license_key == "noassertion":
            repo_license_key = ""

    for file_entry in scan_result.get("files", []):
        if file_entry.get("type") != "file":
            continue
        file_path = file_entry.get("path", "")
        # Salta i lock file / metadati auto-generati (vedi
        # is_excluded_from_license_scan): le licenze che contengono sono
        # quelle delle dipendenze di terze parti, non del codice del progetto.
        if is_excluded_from_license_scan(file_path):
            continue
        detected = file_entry.get("license_detections", []) or file_entry.get("licenses", [])
        for lic in detected:
            lic_key = (lic.get("license_expression") or lic.get("key") or "").lower()
            if not lic_key or not repo_license_key:
                continue
            pair = frozenset({lic_key, repo_license_key})
            if pair in INCOMPATIBLE_PAIRS:
                conflicts.append({
                    "file": file_entry.get("path"),
                    "file_license": lic_key,
                    "repo_license": repo_license_key,
                })
    return conflicts


def detect_copyright_stripping(scan_before: dict, scan_after: dict) -> list[dict]:
    """
    Confronta i campi 'copyrights' rilevati da ScanCode tra due snapshot
    (prima/dopo la PR) dello stesso file. Richiede di aver fatto scan anche
    sulla versione pre-PR (checkout del commit padre).
    """
    stripped = []

    before_by_path = {f["path"]: f for f in scan_before.get("files", []) if f.get("type") == "file"}
    after_by_path = {f["path"]: f for f in scan_after.get("files", []) if f.get("type") == "file"}

    for path, before_entry in before_by_path.items():
        after_entry = after_by_path.get(path)
        if after_entry is None:
            continue  # file rimosso, fuori scope per questa metrica

        before_copyrights = {c.get("copyright") for c in before_entry.get("copyrights", [])}
        after_copyrights = {c.get("copyright") for c in after_entry.get("copyrights", [])}

        removed = before_copyrights - after_copyrights
        if removed:
            stripped.append({
                "file": path,
                "removed_copyright_statements": list(removed),
            })

    return stripped


def main():
    subset_pr = pd.read_parquet(SUBSET_DIR / "subset_pull_requests.parquet")
    fetch_log = pd.read_csv(SUBSET_DIR / "fetch_log.csv")

    license_rows = []
    copyright_rows = []

    for _, pr in subset_pr.iterrows():
        pr_id = pr["id"]
        files_after_dir = PROJECT_ROOT / "data" / "files" / str(pr_id) / "after"
        if not files_after_dir.exists() or not any(files_after_dir.iterdir()):
            continue

        # ScanCode puo' scansionare una cartella di file sparsi (non serve
        # un repo git): qui scansioniamo solo i file toccati dalla PR,
        # quindi la metrica e' attribuibile all'agente.
        scan_after = run_scancode(files_after_dir, pr_id)
        if scan_after is None:
            continue

        # La licenza dichiarata dal progetto e' confermata presente nei
        # metadati AIDev: repository.license (es. "MIT", "Apache-2.0"),
        # disponibile qui come 'repo_license' dopo il join fatto in
        # 01_build_subset.py. E' la fonte primaria, piu' affidabile della
        # scansione del file LICENSE (che potrebbe non essere stato trovato/
        # avere un nome non standard). Lo step di scansione del file LICENSE
        # scaricato da 02_fetch_files.py resta utile come confronto/fallback
        # se repo_license risulta nullo per qualche PR.
        declared_license = pr.get("repo_license")
        conflicts = detect_license_conflicts(scan_after, declared_license)
        for c in conflicts:
            c["pr_id"] = pr_id
            c["agent"] = pr["agent"]
            license_rows.append(c)

        # Copyright stripping: confronto file-per-file tra "before" e "after",
        # entrambi cartelle di file singoli scaricate da 02_fetch_files.py.
        files_before_dir = PROJECT_ROOT / "data" / "files" / str(pr_id) / "before"
        if files_before_dir.exists() and any(files_before_dir.iterdir()):
            scan_before = run_scancode(files_before_dir, f"{pr_id}_before")
            if scan_before is not None:
                stripped = detect_copyright_stripping(scan_before, scan_after)
                for s in stripped:
                    s["pr_id"] = pr_id
                    s["agent"] = pr["agent"]
                    copyright_rows.append(s)

    IP_RIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(license_rows).to_csv(IP_RIGHTS_DIR / "license_conflicts.csv", index=False)
    pd.DataFrame(copyright_rows).to_csv(IP_RIGHTS_DIR / "copyright_stripping.csv", index=False)

    log.info(f"Conflitti di licenza trovati: {len(license_rows)}")
    log.info(f"Casi di copyright stripping trovati: {len(copyright_rows)}")


if __name__ == "__main__":
    main()
