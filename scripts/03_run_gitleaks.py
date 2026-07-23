r"""
03_run_gitleaks.py

Misura il Data Leakage (chiavi API, password, PII, token) usando Gitleaks.

Installazione (una tantum, fuori da questo script):
    Windows: scarica il binario da
        https://github.com/gitleaks/gitleaks/releases
    e mettilo nella root del progetto (o in una cartella a piacere).

PERCORSO DELL'ESEGUIBILE: per default questo script cerca "gitleaks.exe"
nella root del progetto (calcolata automaticamente come la cartella padre
di "scripts/").

Modalita' di scansione:

Scansione sul DIFF della PR
   -> Risponde a: "l'agente ha introdotto un secret in QUESTA PR?"
   -> Ogni patch viene scritta come file .diff in una cartella temporanea e
      l'intera cartella viene scansionata con
      `gitleaks detect --no-git --source <cartella>`.

NOTA IMPLEMENTATIVA (scansione in BATCH):
   Una versione precedente invocava gitleaks UNA VOLTA PER PATCH. Su un
   subset ampio (decine di migliaia di patch) questo approccio diventa
   proibitivo: l'avvio di un processo esterno ha un costo fisso che,
   moltiplicato per il numero di patch, domina completamente il tempo di
   esecuzione (ore invece di minuti). Inoltre i file temporanei venivano
   creati con delete=False e mai rimossi, accumulandosi a decine di migliaia
   nella cartella temp di sistema e degradando ulteriormente le prestazioni.
   La versione attuale scrive tutte le patch in un'unica cartella temporanea
   (un file per patch, con il pr_id codificato nel nome), invoca gitleaks
   UNA SOLA VOLTA sull'intera cartella, e infine ricostruisce l'associazione
   finding -> PR dal nome del file riportato nel report. La cartella
   temporanea viene sempre rimossa a fine esecuzione.

Output: results/subject_rights/gitleaks_findings.jsonl (un record per finding, con pr_id)
        results/subject_rights/gitleaks_summary.csv (conteggio per PR/agente)
"""

import os
import re
import shutil
import subprocess
import json
import pandas as pd
from pathlib import Path
import tempfile
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Root del progetto = cartella padre di "scripts/" (questo file e' in scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
SUBSET_DIR = RESULTS_DIR / "subset"
SUBJECT_RIGHTS_DIR = RESULTS_DIR / "subject_rights"
PATCHES_DIR = PROJECT_ROOT / "data" / "patches"

# Percorso dell'eseguibile Gitleaks: di default lo cerca nella root del
# progetto come "gitleaks.exe" (Windows). Sovrascrivibile con la variabile
# d'ambiente GITLEAKS_PATH se si trova altrove o si chiama solo "gitleaks"
# (macOS/Linux, se nel PATH di sistema).
_default_gitleaks = PROJECT_ROOT / "gitleaks.exe"
GITLEAKS_PATH = os.environ.get(
    "GITLEAKS_PATH",
    str(_default_gitleaks) if _default_gitleaks.exists() else "gitleaks",
)

# Prefisso usato per i file temporanei delle patch. Il pr_id viene codificato
# nel nome del file cosi' da poter ricostruire, dal report di gitleaks,
# quale PR ha generato ciascun finding.
PATCH_FILE_RE = re.compile(r"^pr(?P<pr_id>-?\d+)_(?P<idx>\d+)\.diff$")


def scan_patches_batch(subset_commits: pd.DataFrame) -> list[dict]:
    """
    Scrive tutte le patch in una cartella temporanea e le scansiona con
    UNA SOLA invocazione di gitleaks. Ritorna la lista dei finding, ciascuno
    arricchito con il pr_id di provenienza.

    Il pr_id e' codificato nel nome del file (pr<ID>_<indice>.diff) perche'
    il report di gitleaks indica il file in cui ha trovato il secret, non
    altri metadati: e' il modo piu' semplice e robusto per risalire alla PR.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="gitleaks_patches_"))
    log.info(f"Preparo le patch in {tmp_dir}")

    n_scritte = 0
    try:
        # --- 1. Scrittura delle patch su file ---
        for idx, row in enumerate(subset_commits.itertuples(index=False)):
            patch_text = getattr(row, "patch", None)
            if not patch_text or not isinstance(patch_text, str):
                continue
            pr_id = getattr(row, "pr_id")
            out_file = tmp_dir / f"pr{pr_id}_{idx}.diff"
            # encoding="utf-8" esplicito: senza questo, su Windows Python usa
            # l'encoding di default del sistema (tipicamente cp1252), che non
            # sa rappresentare molti caratteri Unicode presenti in diff e
            # commenti reali (accentate non latine, emoji, simboli speciali),
            # causando un UnicodeEncodeError.
            out_file.write_text(patch_text, encoding="utf-8")
            n_scritte += 1

        log.info(f"Scritte {n_scritte} patch. Avvio la scansione (una sola invocazione)...")

        if n_scritte == 0:
            return []

        # --- 2. Scansione unica dell'intera cartella ---
        report_path = tmp_dir.parent / f"{tmp_dir.name}_report.json"
        cmd = [
            GITLEAKS_PATH, "detect",
            "--no-git",
            "--source", str(tmp_dir),
            "--report-format", "json",
            "--report-path", str(report_path),
            "--exit-code", "0",  # non vogliamo che il processo "fallisca" se trova qualcosa
        ]
        try:
            # Nessun timeout stretto: la scansione di decine di migliaia di
            # file richiede legittimamente qualche minuto.
            subprocess.run(cmd, check=True, capture_output=True, timeout=3600)
        except subprocess.CalledProcessError as e:
            log.error(f"Gitleaks fallito: {e.stderr.decode(errors='ignore')[:500]}")
            return []
        except subprocess.TimeoutExpired:
            log.error("Gitleaks: timeout della scansione batch (oltre 1 ora).")
            return []

        # --- 3. Lettura del report e mappatura finding -> PR ---
        findings = []
        if report_path.exists() and report_path.stat().st_size > 0:
            try:
                raw = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.error("Report di gitleaks non leggibile (JSON malformato).")
                raw = []

            non_mappati = 0
            for item in raw:
                # Il campo "File" contiene il percorso del file temporaneo:
                # da li' si estrae il pr_id codificato nel nome.
                file_field = str(item.get("File", ""))
                basename = Path(file_field).name
                m = PATCH_FILE_RE.match(basename)
                if m:
                    item["pr_id"] = int(m.group("pr_id"))
                    findings.append(item)
                else:
                    non_mappati += 1

            if non_mappati:
                log.warning(
                    f"{non_mappati} finding non associabili a una PR "
                    "(nome file temporaneo inatteso): esclusi."
                )

        if report_path.exists():
            report_path.unlink()

        return findings

    finally:
        # --- 4. Pulizia SEMPRE, anche in caso di errore ---
        # (la versione precedente lasciava sul disco due file per ogni patch,
        # accumulandone decine di migliaia nella cartella temp di sistema)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log.info("Cartella temporanea rimossa.")


def scan_repo_with_gitleaks(repo_path: Path, pr_id) -> list[dict]:
    """Scansiona l'intero albero di file checkoutato (modalita' B, baseline)."""
    report_path = repo_path / "gitleaks_report.json"
    cmd = [
        GITLEAKS_PATH, "detect",
        "--no-git",
        "--source", str(repo_path),
        "--report-format", "json",
        "--report-path", str(report_path),
        "--exit-code", "0",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning(f"Gitleaks (repo mode) fallito su PR {pr_id}: {e}")
        return []

    if report_path.exists() and report_path.stat().st_size > 0:
        raw = json.loads(report_path.read_text(encoding="utf-8"))
        for item in raw:
            item["pr_id"] = pr_id
        return raw
    return []


def main(mode: str = "patch"):
    subset_commits = pd.read_parquet(SUBSET_DIR / "subset_commit_details.parquet")
    subset_pr = pd.read_parquet(SUBSET_DIR / "subset_pull_requests.parquet")

    all_findings = []

    if mode == "patch":
        # FILTRO DI ATTRIBUIBILITA'
        # Il subset dei commit e' costruito "via SHA": si prendono i commit
        # delle PR selezionate e tutte le righe di pr_commit_details relative
        # a quegli SHA. Alcuni commit pero' sono CONDIVISI tra piu' PR (rebase,
        # cherry-pick, branch inclusi in PR diverse): per quelle righe la
        # colonna pr_id di pr_commit_details punta a una PR "primaria" che
        # puo' non appartenere al campione. Un finding rilevato su quelle
        # patch non sarebbe attribuibile ad alcun agente del campione (il
        # merge con subset_pull_requests lascerebbe agent vuoto).
        # Si escludono quindi tali righe, mantenendo lo script coerente con
        # 04 e 05 (che iterano sulle PR del campione) e garantendo che ogni
        # finding sia riconducibile a un agente noto.
        pr_ids_campione = set(subset_pr["id"])
        n_prima = len(subset_commits)
        subset_commits = subset_commits[subset_commits["pr_id"].isin(pr_ids_campione)]
        n_escluse = n_prima - len(subset_commits)
        if n_escluse:
            log.info(
                f"Escluse {n_escluse} righe su {n_prima} ({n_escluse/n_prima:.1%}) "
                "con pr_id esterno al campione (commit condivisi tra PR): "
                "i loro finding non sarebbero attribuibili a un agente."
            )

        all_findings = scan_patches_batch(subset_commits)

    elif mode == "repo":
        for _, pr in subset_pr.iterrows():
            # Coerente con 02_fetch_files.py: niente repo clonato, si usa la
            # cartella dei file scaricati per quella PR (versione "after").
            repo_path = PROJECT_ROOT / "data" / "files" / str(pr["id"]) / "after"
            if not repo_path.exists():
                continue
            findings = scan_repo_with_gitleaks(repo_path, pr["id"])
            all_findings.extend(findings)

    findings_df = pd.DataFrame(all_findings)
    SUBJECT_RIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    findings_df.to_json(SUBJECT_RIGHTS_DIR / "gitleaks_findings.jsonl", orient="records", lines=True)

    if not findings_df.empty:
        summary = findings_df.groupby("pr_id").size().reset_index(name="n_findings")
        summary = summary.merge(subset_pr[["id", "agent"]], left_on="pr_id", right_on="id", how="left")

        # Controllo di sicurezza: dopo il filtro di attribuibilita' non
        # dovrebbero esserci PR senza agente. Se ne compaiono, e' il segnale
        # di un disallineamento tra le tabelle da investigare.
        senza_agente = summary["agent"].isna().sum()
        if senza_agente:
            log.warning(
                f"{senza_agente} PR con finding non hanno un agente associato: "
                "verificare la coerenza tra subset_commit_details e "
                "subset_pull_requests."
            )

        summary.to_csv(SUBJECT_RIGHTS_DIR / "gitleaks_summary.csv", index=False)
        log.info(f"Trovati {len(findings_df)} finding totali su {summary['pr_id'].nunique()} PR")
    else:
        log.info("Nessun finding di leak rilevato nel subset.")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "patch"
    main(mode=mode)