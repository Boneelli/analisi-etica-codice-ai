"""
mostra_finding_gitleaks.py — Estrae i finding di Gitleaks in forma leggibile
per la validazione manuale, raggruppati per tipo di regola.

Non modifica nulla: stampa soltanto.

USO (dalla root del progetto):
    python mostra_finding_gitleaks.py            # tutti, raggruppati
    python mostra_finding_gitleaks.py specifiche # solo le regole a piu' alto rischio
    python mostra_finding_gitleaks.py generic    # solo generic-api-key
    python mostra_finding_gitleaks.py curl       # solo curl-auth-header
"""

import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
FINDINGS = PROJECT_ROOT / "results" / "subject_rights" / "gitleaks_findings.jsonl"

# quali campi contengono il valore rilevato / contesto (variano per versione)
def get_field(row, *names):
    for n in names:
        v = row.get(n)
        if isinstance(v, str) and v.strip():
            return v
    return ""

REGOLE_SPECIFICHE = [
    "stripe-access-token", "private-key", "slack-webhook-url",
    "slack-bot-token", "algolia-api-key",
]

def main():
    df = pd.read_json(FINDINGS, lines=True)

    filtro = sys.argv[1] if len(sys.argv) > 1 else "all"
    if filtro == "specifiche":
        df = df[df["RuleID"].isin(REGOLE_SPECIFICHE)]
        titolo = "REGOLE SPECIFICHE (piu' a rischio di essere veri leak)"
    elif filtro == "generic":
        df = df[df["RuleID"] == "generic-api-key"]
        titolo = "generic-api-key"
    elif filtro == "curl":
        df = df[df["RuleID"] == "curl-auth-header"]
        titolo = "curl-auth-header"
    else:
        titolo = "TUTTI I FINDING"

    print("=" * 75)
    print(titolo)
    print(f"Finding mostrati: {len(df)}")
    print("=" * 75)

    # ordina per regola, poi per PR
    df = df.sort_values(["RuleID", "pr_id"])

    for regola, gruppo in df.groupby("RuleID"):
        print(f"\n{'#'*70}\n# {regola}  ({len(gruppo)} finding)\n{'#'*70}")
        for _, r in gruppo.iterrows():
            file_str = get_field(r, "File")
            # nome file "leggibile": ultima parte dopo l'ultimo __
            file_short = Path(file_str).name if file_str else "?"
            match = get_field(r, "Match", "Secret", "Line")
            secret = get_field(r, "Secret")
            print(f"\n  PR {r['pr_id']} | {file_short[:60]}")
            print(f"    match : {match[:100]}")
            if secret and secret != match:
                print(f"    secret: {secret[:60]}")

    print("\n" + "=" * 75)
    print("Per la validazione, classificare ogni SECRET UNIVOCO come:")
    print("  VP           = vero positivo (segreto reale)")
    print("  FP_test      = chiave in file di test/fixture")
    print("  FP_notsecret = placeholder / esempio / valore finto")
    print("  FP_dev_ci    = chiave di sviluppo o CI non sensibile")
    print("=" * 75)


if __name__ == "__main__":
    main()
