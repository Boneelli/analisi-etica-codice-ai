"""
00_explore_dataset.py

Script di SOLA ESPLORAZIONE.
Serve a verificare i nomi reali delle colonne nelle tabelle di AIDev.



Uso:
    python scripts/00_explore_dataset.py                  # leggero (schema-only per i file pesanti)
    python scripts/00_explore_dataset.py --full            # scarica anche pr_commit_details per intero
"""

import argparse
import pandas as pd
import pyarrow.parquet as pq
import fsspec

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

HF_BASE = "hf://datasets/hao-li/AIDev"


def explore_full(name: str, df: pd.DataFrame, n_rows: int = 3):
    print(f"\n{'='*70}")
    print(f"TABELLA: {name}  (caricata per intero)")
    print(f"{'='*70}")
    print(f"Shape: {df.shape[0]} righe x {df.shape[1]} colonne")
    print(f"\nColonne:\n{df.columns.tolist()}")
    print(f"\nPrime {n_rows} righe:")
    print(df.head(n_rows))
    print(f"\nTipi di dato:\n{df.dtypes}")


def explore_schema_only(name: str, path: str):
    """
    Legge solo lo schema (nomi colonna + tipi) di un file parquet remoto,
    senza scaricarne il contenuto. Utile per file grandi come
    pr_commit_details.parquet quando si vuole solo controllare
    i nomi delle colonne.
    """
    print(f"\n{'='*70}")
    print(f"TABELLA: {name}  (SOLO SCHEMA, nessun download del contenuto)")
    print(f"{'='*70}")

    with fsspec.open(path, "rb") as f:
        parquet_file = pq.ParquetFile(f)
        schema = parquet_file.schema_arrow
        print(f"\nColonne e tipi:\n{schema}")
        print(f"\nNumero totale di righe nel file: {parquet_file.metadata.num_rows}")

    print(
        "\n⚠️ Questa e' solo l'intestazione/schema. Per vedere righe di esempio "
        "con contenuto reale, esegui con --full (scarica l'intero file, ~485 MB "
        "per pr_commit_details) oppure usa lo script 01, che scarica il file "
        "comunque (e' necessario per costruire il subset)."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Esplora lo schema del dataset AIDev")
    parser.add_argument(
        "--full", action="store_true",
        help="Scarica anche pr_commit_details.parquet per intero (~485 MB). "
             "Senza questo flag, di pr_commit_details si legge solo lo schema.",
    )
    args = parser.parse_args()

    print("Carico pull_request.parquet (leggero, ~17 MB) ...")
    pr_df = pd.read_parquet(f"{HF_BASE}/pull_request.parquet")
    explore_full("pull_request", pr_df)

    print("\n\nCarico repository.parquet (leggero, ~6 MB) ...")
    repo_df = pd.read_parquet(f"{HF_BASE}/repository.parquet")
    explore_full("repository", repo_df)

    print("\n\nControllo schema di pr_commit_details.parquet (pesante, ~485 MB)...")
    if args.full:
        print("--full richiesto: scarico il file per intero. Potrebbe richiedere tempo.")
        commit_details_df = pd.read_parquet(f"{HF_BASE}/pr_commit_details.parquet")
        explore_full("pr_commit_details", commit_details_df)
    else:
        explore_schema_only("pr_commit_details", f"{HF_BASE}/pr_commit_details.parquet")

    # Controlli specifici utili per la pipeline (solo su pr_df, leggero):
    print(f"\n\n{'='*70}")
    print("CONTROLLI UTILI PER LA PIPELINE")
    print(f"{'='*70}")

    if "agent" in pr_df.columns:
        print(f"\nAgenti disponibili (colonna 'agent'):\n{pr_df['agent'].value_counts()}")
    else:
        print("\n⚠️ Colonna 'agent' non trovata in pull_request - cercare nome alternativo tra le colonne sopra")

    if "merged_at" in pr_df.columns:
        print(f"\nPR con merged_at non nullo: {pr_df['merged_at'].notna().sum()} / {len(pr_df)}")
    else:
        print("\n⚠️ Colonna 'merged_at' non trovata - cercare nome alternativo per lo stato della PR")

    print("\n⚠️ Verificare manualmente nelle colonne sopra elencate i nomi esatti per:")
    print("   - id della PR (presunto: 'id')")
    print("   - id della PR dentro pr_commit_details (presunto: 'pr_id')")
    print("   - SHA del commit (presunto: 'sha')")
    print("   - contenuto della patch/diff (presunto: 'patch')")
    print("   - nome/percorso del file modificato (presunto: 'filename' o 'file_path')")
    print("   - stato del file: added/modified/removed/renamed (presunto: 'status')")
    print("   - URL della repo (presunto: 'repo_url' dentro pull_request, o da unire con repository)")
    print("   - licenza dichiarata dalla repo (presunto: 'license' dentro repository)")

