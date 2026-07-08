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
   -> Si scansiona il file .patch/.diff prodotto dal commit, con
      `gitleaks detect --no-git -s <file_diff>` oppure si crea un mini-repo
      con un solo commit (quello della PR) e si usa `gitleaks detect`.


Output: results/gitleaks_findings.jsonl (un record per finding, con pr_id)
        results/gitleaks_summary.csv (conteggio per PR/agente)
"""

import os
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


def scan_patch_with_gitleaks(patch_text: str, pr_id) -> list[dict]:
    """
    Scansiona il testo di una patch/diff con gitleaks.
    Gitleaks supporta la scansione di un file di diff puro con --no-git
    quando il contenuto e' in formato unified diff; se la versione installata
    non lo supporta direttamente, l'alternativa robusta e' scrivere il diff
    come file di testo e usare `gitleaks detect --no-git -s <file>`.
    """
    # encoding="utf-8" esplicito: senza questo, su Windows Python usa
    # l'encoding di default del sistema (tipicamente cp1252), che non sa
    # rappresentare molti caratteri Unicode presenti in diff/commenti reali
    # (es. caratteri accentati non latini, emoji, simboli speciali),
    # causando un UnicodeEncodeError. UTF-8 e' la scelta corretta per
    # qualsiasi contenuto di codice moderno, indipendentemente dal sistema.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".diff", delete=False, encoding="utf-8") as f:
        f.write(patch_text)
        patch_path = f.name

    report_path = patch_path + ".report.json"

    cmd = [
        GITLEAKS_PATH, "detect",
        "--no-git",
        "--source", patch_path,
        "--report-format", "json",
        "--report-path", report_path,
        "--exit-code", "0",  # non vogliamo che il processo "fallisca" se trova qualcosa
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    except subprocess.CalledProcessError as e:
        log.warning(f"Gitleaks errore su PR {pr_id}: {e.stderr.decode(errors='ignore')[:200]}")
        return []
    except subprocess.TimeoutExpired:
        log.warning(f"Gitleaks timeout su PR {pr_id}")
        return []

    findings = []
    report_file = Path(report_path)
    if report_file.exists() and report_file.stat().st_size > 0:
        try:
            raw = json.loads(report_file.read_text(encoding="utf-8"))
            for item in raw:
                item["pr_id"] = pr_id
                findings.append(item)
        except json.JSONDecodeError:
            pass

    return findings


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
        # 'patch' e' il nome di colonna presunto: VERIFICARE con commit_details.columns
        for _, row in subset_commits.iterrows():
            patch_text = row.get("patch")
            if not patch_text or not isinstance(patch_text, str):
                continue
            findings = scan_patch_with_gitleaks(patch_text, row["pr_id"])
            all_findings.extend(findings)

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
        summary.to_csv(SUBJECT_RIGHTS_DIR / "gitleaks_summary.csv", index=False)
        log.info(f"Trovati {len(findings_df)} finding totali su {summary['pr_id'].nunique()} PR")
    else:
        log.info("Nessun finding di leak rilevato nel subset.")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "patch"
    main(mode=mode)
