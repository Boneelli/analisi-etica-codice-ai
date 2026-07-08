"""
confronta_validazione.py — Calcola l'accordo umano-judge sulla Fairness.

Da lanciare DOPO aver compilato results/fairness_validazione_CIECO.csv
(le 4 colonne 'mio_*'). Incrocia i tuoi punteggi con quelli del judge
(dalla CHIAVE) e calcola le misure di accordo da riportare in tesi.

USO:
    python confronta_validazione.py
"""

import pandas as pd
import numpy as np
from pathlib import Path

RESULTS = Path("results")
FAIRNESS = RESULTS / "fairness"

cieco = pd.read_csv(FAIRNESS / "fairness_validazione_CIECO.csv")
chiave = pd.read_csv(FAIRNESS / "fairness_validazione_CHIAVE.csv")

DIMENSIONI = [
    ("demographic_fairness", "mio_demographic_fairness", "judge_demographic_fairness"),
    ("accessibility_inclusion", "mio_accessibility_inclusion", "judge_accessibility_inclusion"),
    ("inclusive_language", "mio_inclusive_language", "judge_inclusive_language"),
    ("overall_ethics", "mio_overall_ethics", "judge_overall_ethics"),
]

df = cieco.merge(chiave, on=["pr_id", "agent"], suffixes=("", "_k"))

# Verifica che il foglio sia stato compilato
mio_cols = [m for _, m, _ in DIMENSIONI]
non_compilate = df[mio_cols].isna().all(axis=1).sum()
if non_compilate > 0:
    print(f"[ATTENZIONE] {non_compilate} righe non hanno alcun punteggio 'mio_*' compilato.")
    print("Compila il foglio cieco prima di lanciare il confronto.\n")

print("=" * 64)
print("ACCORDO UMANO-JUDGE — Validazione Fairness")
print("=" * 64)
print(f"PR validate: {len(df)}\n")

righe_stat = []
tutte_diff = []
for nome, mio, judge in DIMENSIONI:
    sub = df[[mio, judge]].dropna()
    if len(sub) == 0:
        continue
    mio_v = sub[mio].astype(float)
    jud_v = sub[judge].astype(float)
    diff = (mio_v - jud_v).abs()
    tutte_diff.extend(diff.tolist())

    esatto = (diff == 0).mean() * 100
    entro1 = (diff <= 1).mean() * 100
    # correlazione (se c'e' varianza)
    corr = mio_v.corr(jud_v) if mio_v.std() > 0 and jud_v.std() > 0 else np.nan

    righe_stat.append({
        "dimensione": nome,
        "n": len(sub),
        "accordo_esatto_%": round(esatto, 1),
        "accordo_entro_1_%": round(entro1, 1),
        "diff_media_assoluta": round(diff.mean(), 2),
        "correlazione": round(corr, 2) if not np.isnan(corr) else "n/d",
    })

stat = pd.DataFrame(righe_stat)
print(stat.to_string(index=False))

# Accordo complessivo su tutte le dimensioni insieme
tutte_diff = np.array(tutte_diff)
print("\n--- Complessivo (tutte le dimensioni) ---")
print(f"Accordo esatto:       {(tutte_diff == 0).mean()*100:.1f}%")
print(f"Accordo entro +/-1:   {(tutte_diff <= 1).mean()*100:.1f}%")
print(f"Differenza media assoluta: {tutte_diff.mean():.2f}")

# Casi di forte disaccordo (utili da discutere in tesi)
print("\n--- Casi di disaccordo forte (differenza >= 2 su qualche dimensione) ---")
disaccordi = []
for _, r in df.iterrows():
    for nome, mio, judge in DIMENSIONI:
        if pd.notna(r[mio]) and pd.notna(r[judge]):
            d = abs(float(r[mio]) - float(r[judge]))
            if d >= 2:
                disaccordi.append({
                    "pr_id": r["pr_id"], "agent": r["agent"],
                    "dimensione": nome, "mio": r[mio], "judge": r[judge], "diff": d,
                })
if disaccordi:
    print(pd.DataFrame(disaccordi).to_string(index=False))
    print("\nQuesti casi meritano un commento in tesi (es. troncamento diff,")
    print("interpretazione diversa della rubrica, ecc.).")
else:
    print("Nessun disaccordo forte (differenza >= 2). Ottimo segno di affidabilita'.")

# Salva il confronto completo
out = df[["pr_id", "agent"] + [m for _, m, _ in DIMENSIONI] + [j for _, _, j in DIMENSIONI]]
out_path = FAIRNESS / "fairness_validazione_CONFRONTO.csv"
out.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\n[Salvato] {out_path}")
