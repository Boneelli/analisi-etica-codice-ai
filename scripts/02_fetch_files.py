"""
02_fetch_files.py

Recupera solo i file necessari all'analisi, senza clonare interi repository:

  1. Per ogni PR, scarica la versione "after" (post-merge) di ogni file
     toccato, via raw.githubusercontent.com.
  2. Se richiesto (per il copyright stripping), scarica anche la versione
     "before" (al commit padre).
  3. Scarica una volta per repo il file di LICENSE/COPYING nella root,
     necessario a ScanCode per il confronto licenza-file vs licenza-progetto.


Limiti da gestire:
  - Rate limit dell'API GitHub (per recuperare lo SHA del commit padre):
    60 req/h senza token, 5000 req/h con un Personal Access Token.
    Impostare GITHUB_TOKEN come variabile d'ambiente.
  - raw.githubusercontent.com non richiede lo stesso token, ma va comunque
    gestito con backoff in caso di errori 429/5xx.
  - File rinominati (status 'renamed'): lo schema di pr_commit_details NON
    ha una colonna 'previous_filename', quindi il path "before" di un file
    rinominato non e' direttamente disponibile. Lo script salta il recupero
    "before" per questi file (li conta nel log ma non scarica nulla),
    per evitare di scaricare accidentalmente il path sbagliato. Da
    rivedere se si scopre, ispezionando i dati reali, un modo per
    ricostruire il path precedente (es. due righe collegate added/removed).
  - File cancellati dalla PR (status 'removed'): non hanno una versione
    "after", solo "before".

Output:
  data/files/<pr_id>/after/<sanitized_path>
  data/files/<pr_id>/before/<sanitized_path>
  data/licenses/<owner>__<repo>/LICENSE* (una sola volta per repo)
  results/fetch_log.csv
"""

import os
import time
import hashlib
import requests
import pandas as pd
from pathlib import Path
from urllib.parse import urlparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
SUBSET_DIR = RESULTS_DIR / "subset"
FILES_DIR = PROJECT_ROOT / "data" / "files"
LICENSES_DIR = PROJECT_ROOT / "data" / "licenses"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API_HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

LICENSE_CANDIDATES = [
    "LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.rst",
    "COPYING", "COPYING.md", "COPYING.txt",
    "LICENCE", "LICENCE.md",
]

SESSION = requests.Session()


def owner_repo_from_api_url(api_url: str) -> tuple[str, str]:
    """'https://api.github.com/repos/owner/repo' -> ('owner', 'repo')"""
    path = urlparse(api_url).path  # /repos/owner/repo
    parts = path.strip("/").split("/")
    return parts[1], parts[2]


def safe_path(path: str) -> str:
    """
    Trasforma un path con / in un nome di file sicuro e FLAT, preservando
    l'estensione originale in coda (Lizard e ScanCode la usano per
    riconoscere il linguaggio/tipo di file).
    Es: 'src/utils/helpers.py' -> 'src__utils__helpers__a1b2c3d4.py'

    ATTENZIONE: i path che arrivano da GitHub sono sempre in stile POSIX
    (separatore '/'), indipendentemente dal sistema operativo locale. Su
    Windows, pathlib.Path interpreta '/' come separatore di directory VALIDO
    e lo ricostruisce internamente con '\\' nativo: questo faceva fallire
    il replace("/", "__") (che non trovava piu' '/' da sostituire, gia'
    convertiti in '\\'), causando un FileNotFoundError al salvataggio perche'
    write_bytes() interpretava il risultato come un path a sotto-cartelle
    inesistenti. Si evita quindi pathlib qui, usando solo operazioni su
    stringa pura per separare stem ed estensione.
    """
    h = hashlib.sha1(path.encode()).hexdigest()[:8]

    # Separazione manuale di stem/suffix, senza pathlib (vedi nota sopra).
    # Prende solo l'ultimo segmento dopo l'ultimo "/" come base per il punto,
    # cosi' eventuali punti nelle cartelle intermedie (raro ma possibile,
    # es. "v1.2/script.py") non confondono l'estensione.
    last_slash = path.rfind("/")
    dir_part = path[:last_slash] if last_slash != -1 else ""
    file_part = path[last_slash + 1:] if last_slash != -1 else path

    last_dot = file_part.rfind(".")
    if last_dot > 0:  # > 0 esclude file come ".gitignore" (dotfile senza estensione "vera")
        suffix = file_part[last_dot:]
        file_stem = file_part[:last_dot]
    else:
        suffix = ""
        file_stem = file_part

    flat_stem = (dir_part + "/" + file_stem).strip("/").replace("/", "__")

    # PROTEZIONE LIMITE LUNGHEZZA (MAX_PATH di Windows = 260 caratteri per il
    # percorso completo). Alcuni file hanno path/nomi molto lunghi (es. gli
    # snapshot di test di Playwright, con nomi >180 caratteri): appiattendoli
    # si otterrebbe un nome file che, sommato al percorso della cartella di
    # destinazione, sfora i 260 caratteri e fa fallire la scrittura con un
    # FileNotFoundError fuorviante. Si tronca quindi lo stem a una lunghezza
    # prudente, mantenendo l'unicita' grazie all'hash finale (calcolato sul
    # path ORIGINALE completo, quindi due file diversi restano distinti anche
    # se i loro nomi troncati coincidessero).
    MAX_STEM_LEN = 120
    if len(flat_stem) > MAX_STEM_LEN:
        # teniamo l'inizio (piu' informativo) e scartiamo il centro/coda lunga
        flat_stem = flat_stem[:MAX_STEM_LEN]

    return f"{flat_stem}__{h}{suffix}"


def fetch_raw_file(owner: str, repo: str, sha: str, path: str, retries: int = 3) -> bytes | None:
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}"
    for attempt in range(retries):
        try:
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.content
            if resp.status_code == 404:
                return None  # file non esiste a quel commit (es. aggiunto/rimosso), normale
            if resp.status_code == 429:
                wait = 2 ** attempt * 5
                log.warning(f"Rate limited su raw URL, attendo {wait}s")
                time.sleep(wait)
                continue
            log.warning(f"Status {resp.status_code} per {url}")
            return None
        except requests.RequestException as e:
            log.warning(f"Errore rete su {url}: {e}")
            time.sleep(2 ** attempt)
    return None


def get_parent_sha(owner: str, repo: str, sha: str) -> str | None:
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
    try:
        resp = SESSION.get(url, headers=GITHUB_API_HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning(f"Impossibile recuperare commit {sha} ({resp.status_code})")
            return None
        data = resp.json()
        parents = data.get("parents", [])
        return parents[0]["sha"] if parents else None
    except requests.RequestException as e:
        log.warning(f"Errore API GitHub per {owner}/{repo}@{sha}: {e}")
        return None


def fetch_license(owner: str, repo: str, sha: str) -> str | None:
    dest_dir = LICENSES_DIR / f"{owner}__{repo}"
    if dest_dir.exists() and any(dest_dir.iterdir()):
        return str(next(dest_dir.iterdir()))

    dest_dir.mkdir(parents=True, exist_ok=True)
    for candidate in LICENSE_CANDIDATES:
        content = fetch_raw_file(owner, repo, sha, candidate)
        if content is not None:
            out_path = dest_dir / candidate
            out_path.write_bytes(content)
            return str(out_path)
    return None


def fetch_pr_files(pr_id, owner: str, repo: str, sha_after: str,
                    file_rows: pd.DataFrame, fetch_before: bool = True) -> list[dict]:

    log_rows = []
    sha_before = None
    if fetch_before:
        sha_before = get_parent_sha(owner, repo, sha_after)

    for _, frow in file_rows.iterrows():
        path = frow.get("filename")
        status = frow.get("status", "modified")
        if not path:
            continue

        entry = {"pr_id": pr_id, "path": path, "status": status}

        # --- versione AFTER ---
        if status != "removed":
            content = fetch_raw_file(owner, repo, sha_after, path)
            if content is not None:
                out_dir = FILES_DIR / str(pr_id) / "after"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / safe_path(path)).write_bytes(content)
                entry["after_fetched"] = True
            else:
                entry["after_fetched"] = False
        else:
            entry["after_fetched"] = "n/a_removed"

        # --- versione BEFORE ---
        if fetch_before and sha_before:
            if status == "renamed":
                # Path "before" sconosciuto con certezza (vedi nota sopra):
                # saltiamo il recupero per evitare di scaricare il path
                # sbagliato silenziosamente.
                entry["before_fetched"] = "skipped_renamed_path_unknown"
            elif status != "added":
                content = fetch_raw_file(owner, repo, sha_before, path)
                if content is not None:
                    out_dir = FILES_DIR / str(pr_id) / "before"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / safe_path(path)).write_bytes(content)
                    entry["before_fetched"] = True
                else:
                    entry["before_fetched"] = False
            else:
                entry["before_fetched"] = "n/a_added"
        else:
            entry["before_fetched"] = "skipped"

        log_rows.append(entry)
        time.sleep(0.05)  # piccolo delay di cortesia, tarare in base al volume

    return log_rows


def github_api_url_to_owner_repo(api_url: str) -> tuple[str, str]:
    return owner_repo_from_api_url(api_url)


def main(fetch_before: bool = True):
    subset_pr = pd.read_parquet(SUBSET_DIR / "subset_pull_requests.parquet")
    subset_commits = pd.read_parquet(SUBSET_DIR / "subset_commit_details.parquet")

    all_log_rows = []

    for _, pr in subset_pr.iterrows():
        pr_id = pr["id"]
        owner, repo = github_api_url_to_owner_repo(pr["repo_url"])

        pr_commits = subset_commits[subset_commits["pr_id"] == pr_id]
        if pr_commits.empty:
            all_log_rows.append({"pr_id": pr_id, "path": None, "status": "no_commits"})
            continue

        sha_after = pr_commits.iloc[-1]["sha"]  # colonna confermata dallo schema ER

        # Licenza del progetto (una volta per repo)
        license_path = fetch_license(owner, repo, sha_after)

        rows = fetch_pr_files(pr_id, owner, repo, sha_after, pr_commits, fetch_before=fetch_before)
        for r in rows:
            r["license_path"] = license_path
        all_log_rows.extend(rows)

    log_df = pd.DataFrame(all_log_rows)
    SUBSET_DIR.mkdir(parents=True, exist_ok=True)
    log_df.to_csv(SUBSET_DIR / "fetch_log.csv", index=False)

    if not log_df.empty and "after_fetched" in log_df.columns:
        success_rate = (log_df["after_fetched"] == True).mean()
        log.info(f"File 'after' recuperati con successo: {success_rate:.1%}")


if __name__ == "__main__":
    main()
