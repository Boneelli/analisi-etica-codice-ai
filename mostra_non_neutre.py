"""
mostra_non_neutre.py — Elenca tutte le PR a cui il judge ha assegnato almeno
un punteggio diverso da 3 (neutro), con i punteggi e il ragionamento.

ATTENZIONE ALLA CECITA' DELLA VALIDAZIONE:
    Questo script mostra i verdetti del judge. NON usarlo mentre si sta
    compilando il foglio cieco (fairness_validazione_CIECO.csv): vedere i
    punteggi del modello prima di assegnare i propri invalida la misura di
    accordo umano-judge, che risulterebbe artificialmente alta.
    Usarlo DOPO aver completato la validazione, per rileggere i casi o per
    riportarli nella discussione dei risultati.

USO (dalla root del progetto):
    python mostra_non_neutre.py                 # tutti i casi non-neutri
    python mostra_non_neutre.py Devin           # solo un agente
    python mostra_non_neutre.py accessibility   # solo una dimensione
    python mostra_non_neutre.py negativi        # solo i punteggi < 3
    python mostra_non_neutre.py positivi        # solo i punteggi > 3
"""

import sys
from pathlib import Path

import pandas as pd

# Su Windows la console usa per default la codifica cp1252, che non sa
# rappresentare emoji e molti simboli Unicode presenti nei testi generati dal
# modello: senza questa riga lo script si interrompe con UnicodeEncodeError.
# errors="replace" sostituisce con '?' i caratteri non rappresentabili invece
# di far fallire la stampa.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

PROJECT_ROOT = Path(__file__).resolve().parent
JUDGE = PROJECT_ROOT / "results" / "fairness" / "llm_judge_fairness.csv"

SCORE_COLS = [
    "score_demographic_fairness",
    "score_accessibility_inclusion",
    "score_inclusive_language",
    "score_overall_ethics",
]
# le tre dimensioni sostanziali (overall_ethics e' una sintesi del modello)
DIM_SOSTANZIALI = SCORE_COLS[:3]

REASONING_COLS = [
    "reasoning_evidenze",
    "reasoning_analisi_etica",
    "reasoning_valutazione_impatto",
]


def campo(riga, nome, default=""):
    v = riga.get(nome, default)
    if pd.isna(v):
        return default
    return str(v)


def main():
    df = pd.read_csv(JUDGE)
    mask = (df[SCORE_COLS] != 3).any(axis=1)
    nn = df[mask].copy()

    filtro = sys.argv[1] if len(sys.argv) > 1 else None
    etichetta = "TUTTE LE PR NON-NEUTRE"

    if filtro:
        f = filtro.lower()
        if f in {"negativi", "negativo", "neg"}:
            nn = nn[(nn[DIM_SOSTANZIALI] < 3).any(axis=1)]
            etichetta = "CASI NEGATIVI (punteggio < 3)"
        elif f in {"positivi", "positivo", "pos"}:
            nn = nn[(nn[DIM_SOSTANZIALI] > 3).any(axis=1)]
            etichetta = "CASI POSITIVI (punteggio > 3)"
        elif f in {"demographic", "demografica"}:
            nn = nn[nn["score_demographic_fairness"] != 3]
            etichetta = "DIMENSIONE: fairness demografica"
        elif f in {"accessibility", "accessibilita", "accessibilita'"}:
            nn = nn[nn["score_accessibility_inclusion"] != 3]
            etichetta = "DIMENSIONE: accessibilita'"
        elif f in {"inclusive", "linguaggio", "language"}:
            nn = nn[nn["score_inclusive_language"] != 3]
            etichetta = "DIMENSIONE: linguaggio inclusivo"
        else:
            # interpretato come nome di agente
            nn = nn[nn["agent"].str.lower() == f]
            etichetta = f"AGENTE: {filtro}"

    nn = nn.sort_values(["agent", "pr_id"])

    print("=" * 78)
    print(etichetta)
    print(f"PR mostrate: {len(nn)} (su {int(mask.sum())} non-neutre totali)")
    print("=" * 78)

    if nn.empty:
        print("\nNessuna PR corrisponde al filtro.")
        return

    for _, r in nn.iterrows():
        print(f"\n{'#'*78}")
        print(f"# PR {r['pr_id']}  [{r['agent']}]")
        print(f"{'#'*78}")
        print("  punteggi (3 = neutro):")
        for c in SCORE_COLS:
            val = r[c]
            nome = c.replace("score_", "")
            segno = ""
            if val < 3:
                segno = "  <-- negativo"
            elif val > 3:
                segno = "  <-- positivo"
            print(f"    {nome:26} {val}{segno}")

        for c in REASONING_COLS:
            testo = campo(r, c)
            if not testo:
                continue
            titolo = c.replace("reasoning_", "").replace("_", " ").upper()
            print(f"\n  {titolo}:")
            # a capo ogni ~95 caratteri per leggibilita'
            parole = testo.split()
            riga = "    "
            for p in parole:
                if len(riga) + len(p) > 95:
                    print(riga)
                    riga = "    "
                riga += p + " "
            if riga.strip():
                print(riga)

    # riepilogo finale
    print("\n" + "=" * 78)
    print("RIEPILOGO")
    print("=" * 78)
    for c in DIM_SOSTANZIALI:
        nome = c.replace("score_", "")
        neg = int((nn[c] < 3).sum())
        pos = int((nn[c] > 3).sum())
        print(f"  {nome:26} negativi: {neg:3}   positivi: {pos:3}")
    print()
    print("  Per agente:")
    print(nn["agent"].value_counts().to_string())


if __name__ == "__main__":
    main()