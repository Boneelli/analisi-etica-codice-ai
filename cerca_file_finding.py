"""
cerca_file_finding.py — Risale al FILE ORIGINALE in cui compare un secret
rilevato da Gitleaks.

PERCHE' SERVE: con la scansione in batch (03_run_gitleaks.py) il campo "File"
del report contiene il nome del file temporaneo (pr<ID>_<idx>.diff), non il
percorso del file nel repository. Per validare a mano un finding serve pero'
sapere DOVE si trova (un test, la documentazione, un file di configurazione,
codice di produzione): e' l'informazione che distingue un falso positivo da un
vero leak.

COME FUNZIONA: cerca il valore del secret dentro le patch di quella PR
(subset_commit_details.parquet) e riporta il nome del file (colonna 'filename')
e qualche riga di contesto attorno alla riga incriminata.

Non modifica nulla: stampa soltanto.

USO (dalla root del progetto):
    python cerca_file_finding.py               # tutti i gruppi ancora da validare
    python cerca_file_finding.py 56f2d4a1      # un gruppo specifico
    python cerca_file_finding.py 56f2d4a1 c591a714   # piu' gruppi
"""

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
VALIDAZIONE = PROJECT_ROOT / "results" / "subject_rights" / "gitleaks_validazione.csv"
COMMITS = PROJECT_ROOT / "results" / "subset" / "subset_commit_details.parquet"

CONTESTO_RIGHE = 3   # righe di contesto prima/dopo la riga trovata


def trova_colonna(df, *candidati, escludi=()):
    """
    Trova il nome reale di una colonna tra piu' varianti possibili.
    'escludi' evita che una colonna gia' assegnata ad altro venga ripescata:
    serve perche' il match parziale su "secret" catturerebbe anche
    "secret_group", che e' l'identificativo del gruppo, non il valore.
    """
    for c in candidati:
        if c in df.columns and c not in escludi:
            return c
    # match parziale, case-insensitive
    for c in df.columns:
        if c in escludi:
            continue
        for cand in candidati:
            if cand.lower() in c.lower():
                return c
    return None


def chiave_ricerca(secret: str) -> str:
    """
    Estrae dal secret una sottostringa distintiva da cercare nelle patch.
    Gestisce i secret multiriga (es. chiavi private) e i prefissi di diff
    ('+' / '-') che non compaiono nel valore ma nella patch si'.
    """
    righe = []
    for r in str(secret).splitlines():
        r = r.lstrip("+-").strip()
        # scarta le righe di delimitazione, poco distintive
        if not r or r.startswith("-----") or r == "...":
            continue
        righe.append(r)
    if not righe:
        return ""
    # la riga piu' lunga e' tipicamente la piu' distintiva
    piu_lunga = max(righe, key=len)
    return piu_lunga[:40]


def mostra_contesto(patch: str, chiave: str, filename: str, status: str):
    righe = str(patch).splitlines()
    trovata = None
    for i, r in enumerate(righe):
        if chiave in r:
            trovata = i
            break
    print(f"    FILE: {filename}")
    print(f"    status: {status}")
    if trovata is None:
        return
    inizio = max(0, trovata - CONTESTO_RIGHE)
    fine = min(len(righe), trovata + CONTESTO_RIGHE + 1)
    print("    contesto:")
    for i in range(inizio, fine):
        marcatore = "  >>" if i == trovata else "    "
        print(f"    {marcatore} {righe[i][:110]}")


def main():
    val = pd.read_csv(VALIDAZIONE)
    col_group = trova_colonna(val, "secret_group", "group")
    col_pr = trova_colonna(val, "pr_id")
    # esclude col_group: senza questo, "secret" matcherebbe "secret_group"
    col_secret = trova_colonna(val, "secret", "secret_value", "valore",
                               escludi=(col_group,))
    col_cat = trova_colonna(val, "categoria_finale")
    col_rule = trova_colonna(val, "RuleID", "rule")
    col_match = trova_colonna(val, "match", "riga", "line",
                              escludi=(col_group, col_secret))

    print("Colonne rilevate nel CSV di validazione:")
    print(f"  gruppo: {col_group} | pr_id: {col_pr} | secret: {col_secret}")

    if not all([col_group, col_pr, col_secret]):
        print("Colonne non riconosciute nel CSV di validazione.")
        print("Colonne trovate:", list(val.columns))
        return

    gruppi_richiesti = sys.argv[1:]
    if gruppi_richiesti:
        sel = val[val[col_group].astype(str).isin(gruppi_richiesti)]
        titolo = f"GRUPPI RICHIESTI ({len(gruppi_richiesti)})"
    else:
        # solo quelli senza categoria_finale compilata
        if col_cat and col_cat in val.columns:
            sel = val[val[col_cat].isna() | (val[col_cat].astype(str).str.strip() == "")]
        else:
            sel = val
        titolo = "GRUPPI ANCORA DA VALIDARE"

    # un rappresentante per gruppo
    sel = sel.drop_duplicates(subset=[col_group])

    print("=" * 72)
    print(titolo)
    print(f"Gruppi da esaminare: {len(sel)}")
    print("=" * 72)

    if sel.empty:
        print("\nNessun gruppo da esaminare.")
        return

    commits = pd.read_parquet(COMMITS)
    col_fn = trova_colonna(commits, "filename", "path")
    col_st = trova_colonna(commits, "status")

    for _, riga in sel.iterrows():
        gruppo = riga[col_group]
        pr_id = riga[col_pr]
        secret = riga[col_secret]
        rule = riga[col_rule] if col_rule else "?"

        print(f"\n{'#'*72}")
        print(f"# gruppo {gruppo} | PR {pr_id} | {rule}")
        print(f"{'#'*72}")
        anteprima = str(secret).replace("\n", " ")[:90]
        print(f"  secret: {anteprima}")

        chiave = chiave_ricerca(secret)
        if not chiave:
            print("  (impossibile costruire una chiave di ricerca)")
            continue

        patch_pr = commits[commits["pr_id"] == pr_id]
        trovati = 0
        for _, c in patch_pr.iterrows():
            patch = c.get("patch")
            if not isinstance(patch, str) or chiave not in patch:
                continue
            trovati += 1
            print()
            mostra_contesto(
                patch,
                chiave,
                c.get(col_fn, "?") if col_fn else "?",
                c.get(col_st, "?") if col_st else "?",
            )
            if trovati >= 3:      # bastano pochi esempi
                print("    (altre occorrenze omesse)")
                break

        if trovati == 0:
            # Ripiego: cerca con la riga completa (colonna 'match'), utile
            # quando il valore del secret e' troncato o normalizzato.
            if col_match:
                chiave2 = chiave_ricerca(riga.get(col_match, ""))
                if chiave2 and chiave2 != chiave:
                    for _, c in patch_pr.iterrows():
                        patch = c.get("patch")
                        if not isinstance(patch, str) or chiave2 not in patch:
                            continue
                        trovati += 1
                        print()
                        mostra_contesto(
                            patch, chiave2,
                            c.get(col_fn, "?") if col_fn else "?",
                            c.get(col_st, "?") if col_st else "?",
                        )
                        break

        if trovati == 0:
            print("  Nessuna patch trovata con questo valore.")
            print(f"  (chiave cercata: {chiave[:50]})")

    print("\n" + "=" * 72)
    print("Guardare il PERCORSO del file per classificare:")
    print("  test/, spec/, __tests__/, fixtures/  -> FP_test")
    print("  docs/, README, esempi                -> FP_notsecret")
    print("  docker-compose, .env.example, CI     -> FP_dev_ci")
    print("  src/, config di produzione           -> possibile VP")
    print("=" * 72)


if __name__ == "__main__":
    main()
