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
  - TUTTE le PR non-neutre (punteggio != 3 su qualche dimensione): sono i casi
    che verranno citati nei risultati, quindi vanno verificati tutti.
  - N_NEUTRE PR neutre scelte casualmente e bilanciate tra i 5 agenti: servono
    a scoprire eventuali FALSI NEGATIVI (problemi che il judge ha dato per
    neutri ma che magari non lo erano).
  - Seed fisso (RIPRODUCIBILITA': lo stesso campione e' rigenerabile).

RIPORTO DELLE VALIDAZIONI PRECEDENTI:
  Se esiste il foglio cieco di una campagna precedente (es. quella sulle prime
  250 PR), i punteggi umani gia' assegnati vengono ricopiati nel nuovo foglio
  e la riga viene marcata come gia' validata. Questo evita di rivalutare a mano
  PR gia' giudicate: i punteggi del judge per quelle PR non sono cambiati, dato
  che l'ampliamento del campione ha solo AGGIUNTO PR senza rivalutare le
  precedenti. Le righe da compilare restano solo quelle nuove.

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
# Numero di PR NEUTRE da aggiungere al campione (le non-neutre sono incluse
# tutte). Servono a stimare i falsi negativi del judge. Si prendono, quando
# possibile, tra quelle gia' validate in campagne precedenti.
N_NEUTRE = 16
SCORE_COLS = [
    "score_demographic_fairness", "score_accessibility_inclusion",
    "score_inclusive_language", "score_overall_ethics",
]
COL_MIE = [
    "mio_demographic_fairness", "mio_accessibility_inclusion",
    "mio_inclusive_language", "mio_overall_ethics", "mie_note",
]
# Fogli ciechi di campagne precedenti da cui recuperare i giudizi gia' dati.
# Si prova piu' di un nome perche' dipende da come e' stato salvato il backup.
VALIDAZIONI_PRECEDENTI = [
    "fairness_validazione_CIECO_250PR.csv",
    "fairness_validazione_CIECO_250.csv",
    "fairness_validazione_CIECO_PILOTA.csv",
    "fairness_validazione_CIECO_10k.csv",
]

judge = pd.read_csv(FAIRNESS / "llm_judge_fairness.csv")
subset = pd.read_parquet(SUBSET / "subset_pull_requests.parquet")
commits = pd.read_parquet(SUBSET / "subset_commit_details.parquet")

# --- 1. Identifica le PR non-neutre (tutte incluse nel campione) ---
mask_non_neutre = (judge[SCORE_COLS] != 3).any(axis=1)
non_neutre = judge[mask_non_neutre].copy()
n_non_neutre = len(non_neutre)
print(f"PR non-neutre (tutte incluse): {n_non_neutre}")

# --- 1b. Carica le validazioni gia' fatte in campagne precedenti ---
gia_validate = {}
for nome in VALIDAZIONI_PRECEDENTI:
    p = FAIRNESS / nome
    if not p.exists():
        continue
    try:
        prec = pd.read_csv(p)
    except Exception:
        continue
    if "pr_id" not in prec.columns:
        continue
    for _, r in prec.iterrows():
        # tiene solo le righe effettivamente compilate
        val = {c: r.get(c, "") for c in COL_MIE if c in prec.columns}
        punteggi = [val.get(c) for c in COL_MIE[:4]]
        if all(pd.isna(v) or str(v).strip() == "" for v in punteggi):
            continue
        gia_validate[r["pr_id"]] = val
    print(f"Recuperate {len(gia_validate)} validazioni da {nome}")
    break
if not gia_validate:
    print("Nessuna validazione precedente trovata: il foglio sara' tutto da compilare.")

# --- 2. Seleziona le neutre ---
# Si privilegiano le PR neutre GIA' VALIDATE in una campagna precedente: sono
# giudizi umani gia' disponibili, quindi ampliano la base di confronto senza
# lavoro manuale aggiuntivo. Restano un campione casuale legittimo di PR
# neutre: erano state estratte a sorte (bilanciate per agente) dal
# sottoinsieme di 250 PR, a sua volta campione stratificato casuale delle
# 1000. I loro punteggi del judge non sono cambiati, perche' l'ampliamento
# del campione ha solo aggiunto PR senza rivalutare le precedenti.
neutre = judge[~mask_non_neutre].copy()
neutre_validate = neutre[neutre["pr_id"].isin(gia_validate.keys())]
print(f"PR neutre gia' validate disponibili: {len(neutre_validate)}")

n_agenti = judge["agent"].nunique()
per_agente = max(1, N_NEUTRE // n_agenti)

campioni_neutre = []
for agente, gruppo in neutre_validate.groupby("agent"):
    n = min(per_agente, len(gruppo))
    campioni_neutre.append(gruppo.sample(n=n, random_state=SEED))
neutre_camp = pd.concat(campioni_neutre) if campioni_neutre else neutre.head(0)

# completa fino a N_NEUTRE, prima con altre gia' validate, poi - solo se non
# bastano - con neutre estratte a sorte tra tutte (queste andranno compilate)
gia_scelte = set(neutre_camp["pr_id"])
mancanti = N_NEUTRE - len(neutre_camp)
if mancanti > 0:
    resto_val = neutre_validate[~neutre_validate["pr_id"].isin(gia_scelte)]
    if len(resto_val) > 0:
        n = min(mancanti, len(resto_val))
        neutre_camp = pd.concat([neutre_camp, resto_val.sample(n=n, random_state=SEED)])
        gia_scelte = set(neutre_camp["pr_id"])
        mancanti = N_NEUTRE - len(neutre_camp)

if mancanti > 0:
    print(f"Le neutre gia' validate non bastano: ne servono altre {mancanti} "
          "estratte a sorte (da compilare a mano).")
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

    precedente = gia_validate.get(pr_id)
    riga_cieco = {
        "pr_id": pr_id,
        "agent": r["agent"],
        "title": title,
        "body": body,
        "diff": get_diff(pr_id),
        # colonne da compilare a mano (precompilate se gia' validate prima):
        "mio_demographic_fairness": "",
        "mio_accessibility_inclusion": "",
        "mio_inclusive_language": "",
        "mio_overall_ethics": "",
        "mie_note": "",
        "gia_validata": "",
    }
    if precedente:
        for c in COL_MIE:
            v = precedente.get(c, "")
            riga_cieco[c] = "" if pd.isna(v) else v
        riga_cieco["gia_validata"] = "SI"
    rows_cieco.append(riga_cieco)
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

n_precompilate = int((cieco["gia_validata"] == "SI").sum())
n_da_fare = len(cieco) - n_precompilate

print()
print(f"[Salvato] {cieco_path}")
print(f"          Righe totali: {len(cieco)}")
print(f"          - gia' validate in precedenza (precompilate): {n_precompilate}")
print(f"          - DA COMPILARE a mano:                        {n_da_fare}")
print(f"          Valuta con la STESSA rubrica del prompt del judge,")
print(f"          SENZA guardare la chiave. Scala 1-5, neutro=3.")
print(f"[Salvato] {chiave_path}")
print(f"          -> NON aprire finche' non hai finito. Serve per il confronto.")
print()
print("Quando hai compilato il foglio cieco, lancia confronta_validazione.py")