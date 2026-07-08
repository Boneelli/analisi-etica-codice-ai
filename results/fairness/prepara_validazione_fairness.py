"""
prepara_validazione_fairness.py — Prepara la validazione manuale (accordo umano-judge)
del judge di Fairness, come richiesto dal tutor.

Genera un campione stratificato di ~25 PR e due file:
  1. results/fairness_validazione_CIECO.csv
     -> il foglio da compilare A MANO: per ogni PR mostra titolo, descrizione
        e diff, con 4 colonne VUOTE per i tuoi punteggi. NON contiene i
        punteggi del judge (validazione "cieca", per non farti influenzare).
  2. results/fairness_validazione_CHIAVE.csv
     -> i punteggi del judge, tenuti da parte. NON aprirlo finche' non hai
        finito di compilare il foglio cieco. Serve per il confronto finale.

COMPOSIZIONE DEL CAMPIONE:
  - TUTTE le PR non-neutre (punteggio != 3 su qualche dimensione): i casi
    "positivi" da verificare.
  - Il resto fino a ~25, scelte casualmente tra le PR neutre, bilanciate tra
    i 5 agenti: servono a scoprire eventuali FALSI NEGATIVI (problemi che il
    judge ha dato per neutri ma che magari non lo erano).
  - Seed fisso (RIPRODUCIBILITA': lo stesso campione e' rigenerabile).

USO:
    python prepara_validazione_fairness.py
"""

import pandas as pd
from pathlib import Path

RESULTS = Path("results")
SUBSET = RESULTS / "subset"
FAIRNESS = RESULTS / "fairness"
FAIRNESS.mkdir(parents=True, exist_ok=True)
SEED = 42
N_TOTALE = 25
SCORE_COLS = [
    "score_demographic_fairness", "score_accessibility_inclusion",
    "score_inclusive_language", "score_overall_ethics",
]

judge = pd.read_csv(FAIRNESS / "llm_judge_fairness.csv")
subset = pd.read_parquet(SUBSET / "subset_pull_requests.parquet")
commits = pd.read_parquet(SUBSET / "subset_commit_details.parquet")

# --- 1. Identifica le PR non-neutre (tutte incluse nel campione) ---
mask_non_neutre = (judge[SCORE_COLS] != 3).any(axis=1)
non_neutre = judge[mask_non_neutre].copy()
n_non_neutre = len(non_neutre)
print(f"PR non-neutre (tutte incluse): {n_non_neutre}")

# --- 2. Campiona le neutre, bilanciando per agente ---
neutre = judge[~mask_non_neutre].copy()
n_da_campionare = N_TOTALE - n_non_neutre
n_agenti = judge["agent"].nunique()
per_agente = max(1, n_da_campionare // n_agenti)

campioni_neutre = []
for agente, gruppo in neutre.groupby("agent"):
    n = min(per_agente, len(gruppo))
    campioni_neutre.append(gruppo.sample(n=n, random_state=SEED))
neutre_camp = pd.concat(campioni_neutre)

# se per arrotondamento non arriviamo a N_TOTALE, aggiungiamo altre neutre a caso
gia_scelte = set(neutre_camp["pr_id"])
mancanti = N_TOTALE - n_non_neutre - len(neutre_camp)
if mancanti > 0:
    resto = neutre[~neutre["pr_id"].isin(gia_scelte)].sample(
        n=min(mancanti, len(neutre) - len(neutre_camp)), random_state=SEED
    )
    neutre_camp = pd.concat([neutre_camp, resto])

# --- 3. Componi il campione finale ---
campione = pd.concat([non_neutre, neutre_camp]).drop_duplicates("pr_id")
# mescola l'ordine (cosi' nel foglio non sono raggruppate non-neutre/neutre:
# altrimenti si "indovina" quali sono le sospette)
campione = campione.sample(frac=1, random_state=SEED).reset_index(drop=True)
print(f"Campione totale: {len(campione)} PR")
print("Distribuzione per agente:")
print(campione["agent"].value_counts().to_string())

# --- 4. Recupera titolo, descrizione, diff per ogni PR del campione ---
def get_diff(pr_id):
    pr_commits = commits[commits["pr_id"] == pr_id]
    if pr_commits.empty:
        return ""
    diff = "\n".join(pr_commits["patch"].dropna().astype(str).tolist())
    return diff

subset_idx = subset.set_index("id")
rows_cieco = []
rows_chiave = []
for _, r in campione.iterrows():
    pr_id = r["pr_id"]
    try:
        info = subset_idx.loc[pr_id]
        title = info["title"] if "title" in info else ""
        body = info["body"] if "body" in info else ""
    except KeyError:
        title, body = "", ""

    rows_cieco.append({
        "pr_id": pr_id,
        "agent": r["agent"],
        "title": title,
        "body": body,
        "diff": get_diff(pr_id),
        # colonne VUOTE da compilare a mano:
        "mio_demographic_fairness": "",
        "mio_accessibility_inclusion": "",
        "mio_inclusive_language": "",
        "mio_overall_ethics": "",
        "mie_note": "",
    })
    rows_chiave.append({
        "pr_id": pr_id,
        "agent": r["agent"],
        "judge_demographic_fairness": r["score_demographic_fairness"],
        "judge_accessibility_inclusion": r["score_accessibility_inclusion"],
        "judge_inclusive_language": r["score_inclusive_language"],
        "judge_overall_ethics": r["score_overall_ethics"],
    })

cieco = pd.DataFrame(rows_cieco)
chiave = pd.DataFrame(rows_chiave)

cieco_path = FAIRNESS / "fairness_validazione_CIECO.csv"
chiave_path = FAIRNESS / "fairness_validazione_CHIAVE.csv"
cieco.to_csv(cieco_path, index=False, encoding="utf-8-sig")
chiave.to_csv(chiave_path, index=False, encoding="utf-8-sig")

print()
print(f"[Salvato] {cieco_path}")
print(f"          -> DA COMPILARE a mano (4 colonne 'mio_*' + note).")
print(f"          -> Valuta con la STESSA rubrica del prompt del judge,")
print(f"             SENZA guardare la chiave. Scala 1-5, neutro=3.")
print(f"[Salvato] {chiave_path}")
print(f"          -> NON aprire finche' non hai finito. Serve per il confronto.")
print()
print("Quando hai compilato il foglio cieco, lancia confronta_validazione.py")
