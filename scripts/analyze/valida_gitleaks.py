"""
valida_gitleaks.py — Prepara un foglio di validazione manuale dei finding Gitleaks.

Genera results/gitleaks_validazione.csv con una riga per finding, contenente:
  - il valore reale del match/secret (IN CHIARO: serve per validare — il file
    resta in locale, non condividerlo cosi' com'e')
  - un ID di segreto univoco (secret_group) per riconoscere i DUPLICATI: lo
    stesso segreto puo' comparire in piu' finding perche' lo stesso diff appare
    in piu' commit/PR
  - una classificazione PRELIMINARE automatica (suggerimento da confermare)
  - colonne vuote 'categoria_finale' e 'note' da compilare a mano

Categorie suggerite per 'categoria_finale':
  VP            = Vero Positivo (segreto di produzione reale)
  FP_test       = Falso Positivo - placeholder/valore di test
  FP_dev_ci     = Falso Positivo - chiave di sviluppo/CI (reale ma non produzione)
  FP_notsecret  = Falso Positivo - non e' un segreto (hash, uuid, chiave pubblica nota)
  revocato      = segreto reale ma gia' revocato/rotato

USO (sul PC dove sta results/):
    python valida_gitleaks.py
"""

import pandas as pd
import hashlib
from pathlib import Path

# Percorso assoluto della cartella results, calcolato dalla posizione di questo
# file (scripts/analyze/valida_gitleaks.py): due .parent risalgono alla root del
# progetto. Cosi' lo script funziona da qualsiasi cartella lo si lanci.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = PROJECT_ROOT / "results"
SUBSET = RESULTS / "subset"
SUBJECT_RIGHTS = RESULTS / "subject_rights"
SUBSET.mkdir(parents=True, exist_ok=True)
SUBJECT_RIGHTS.mkdir(parents=True, exist_ok=True)

gl = pd.read_json(SUBJECT_RIGHTS / "gitleaks_findings.jsonl", lines=True)

# Recupero agente da CSV che ce l'hanno
def load_map():
    m = {}
    for p in [RESULTS / "sustainability" / "lizard_metrics.csv",
              RESULTS / "sustainability" / "green_smell_density.csv",
              SUBJECT_RIGHTS / "gitleaks_summary.csv"]:
        if p.exists():
            d = pd.read_csv(p)
            if "pr_id" in d.columns and "agent" in d.columns:
                m.update(d[["pr_id", "agent"]].drop_duplicates().set_index("pr_id")["agent"].to_dict())
    return m

# se c'e' il parquet completo, meglio
try:
    pr = pd.read_parquet(SUBSET / "subset_pull_requests.parquet")
    pr2agent = pr.set_index("id")["agent"].to_dict()
except Exception:
    pr2agent = load_map()

gl["agent"] = gl["pr_id"].map(pr2agent)

# ID di gruppo per segreto univoco: stesso Secret => stesso gruppo (rileva duplicati)
def secret_group(s):
    return hashlib.sha1(str(s).encode()).hexdigest()[:8]

gl["secret_group"] = gl["Secret"].apply(secret_group)


def classifica_preliminare(row):
    """Classificazione automatica di primo livello, da confermare a mano.
    Riconosce i pattern piu' evidenti di falso positivo."""
    secret = str(row["Secret"]).lower()
    match = str(row["Match"]).lower()

    # placeholder/test evidenti
    placeholder_hints = ["test", "example", "placeholder", "your-", "changeme",
                         "dummy", "sample", "xxx", "1234", "sk-123", "my-secret",
                         "fake", "foo", "bar", "<", "abcd"]
    if any(h in secret for h in placeholder_hints) or any(h in match for h in placeholder_hints):
        return "FP_test?"

    # chiave pubblica nota dell'emulatore CosmosDB di Azure (universalmente documentata)
    if secret.startswith("c2y6yd") or "cosmos" in match:
        return "FP_notsecret?(cosmos-emulator)"

    # ENCRYPTION_KEY / chiavi in config di dev-CI (da verificare nel contesto)
    if "encryption_key" in match or "encryption" in match:
        return "FP_dev_ci?"

    # chiave privata: forma reale, ma spesso di test — da guardare nel contesto
    if row["RuleID"] == "private-key":
        return "?(private-key: verificare se di test)"

    # esadecimale che parte con 0x + sequenza => spesso esempio
    if secret.startswith("0x1234") or secret.startswith("0xabcd"):
        return "FP_test?(hex sequenziale)"

    return "?(da validare)"


gl["classificazione_auto"] = gl.apply(classifica_preliminare, axis=1)
gl["categoria_finale"] = ""   # da compilare a mano
gl["note"] = ""               # da compilare a mano

# Ordino per raggruppare i duplicati vicini
gl_sorted = gl.sort_values(["secret_group", "agent"]).reset_index(drop=True)

# Colonne del foglio di validazione (Match e Secret IN CHIARO)
cols = ["secret_group", "agent", "pr_id", "RuleID", "Match", "Secret",
        "classificazione_auto", "categoria_finale", "note"]
foglio = gl_sorted[cols]

out_path = SUBJECT_RIGHTS / "gitleaks_validazione.csv"
foglio.to_csv(out_path, index=False, encoding="utf-8-sig")  # utf-8-sig: si apre bene in Excel

# Riepilogo a schermo
n_tot = len(gl)
n_unici = gl["secret_group"].nunique()
print(f"Finding totali: {n_tot}")
print(f"Segreti UNIVOCI (dopo deduplicazione): {n_unici}")
print(f"  -> {n_tot - n_unici} finding sono duplicati dello stesso segreto")
print()
print("Segreti univoci per agente (conteggio deduplicato):")
dedup = gl.drop_duplicates("secret_group")
print(dedup["agent"].value_counts().to_string())
print()
print("Classificazione automatica preliminare (da confermare a mano):")
print(dedup["classificazione_auto"].value_counts().to_string())
print()
print(f"[Salvato] {out_path}")
print()
print("PROSSIMO PASSO: apri il CSV, per ogni riga compila 'categoria_finale'")
print("con una di: VP, FP_test, FP_dev_ci, FP_notsecret, revocato")
print("(puoi validare un solo finding per secret_group e copiare la stessa")
print(" categoria sui suoi duplicati). Poi lanciamo lo script di conteggio.")
