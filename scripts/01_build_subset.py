"""
01_build_subset.py

Costruisce il subset di Pull Request da analizzare a partire dal dataset AIDev
(https://huggingface.co/datasets/hao-li/AIDev).

Il join corretto per ottenere "tutti i file/patch di una PR" e':
  pull_request.id == pr_commits.pr_id  ->  pr_commits.sha == pr_commit_details.sha
(pr_commit_details ha anche una propria colonna pr_id, potenzialmente ridondante
con quella ottenuta via pr_commits - usare quella direttamente se popolata,
verificare con 00_explore_dataset.py se i due path danno lo stesso risultato)


Output: results/subset_pull_requests.parquet con le PR selezionate
        results/subset_commit_details.parquet con le patch corrispondenti
"""

import pandas as pd
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_aidev_pop():
    """Carica le tabelle della sotto-versione AIDev-pop (>100 stelle)."""
    pr_df = pd.read_parquet("hf://datasets/hao-li/AIDev/pull_request.parquet")
    repo_df = pd.read_parquet("hf://datasets/hao-li/AIDev/repository.parquet")
    pr_commits_df = pd.read_parquet("hf://datasets/hao-li/AIDev/pr_commits.parquet")
    commit_details_df = pd.read_parquet(
        "hf://datasets/hao-li/AIDev/pr_commit_details.parquet"
    )
    return pr_df, repo_df, pr_commits_df, commit_details_df


def build_subset(
    pr_df: pd.DataFrame,
    repo_df: pd.DataFrame,
    pr_commits_df: pd.DataFrame,
    commit_details_df: pd.DataFrame,
    agents: list[str],
    n_per_agent: int,
    only_merged: bool = True,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:

    df = pr_df.copy()

    if only_merged:
        df = df[df["merged_at"].notna()]

    if agents:
        df = df[df["agent"].isin(agents)]

    # Teniamo solo le PR per cui esiste almeno un commit in pr_commits
    # (tabella ponte verso pr_commit_details, dove stanno le patch)
    prs_with_commits = set(pr_commits_df["pr_id"].unique())
    df = df[df["id"].isin(prs_with_commits)]

    # Campionamento stratificato per agente.
    # NOTA IMPORTANTE: in pandas 3.x, groupby("agent", group_keys=False).apply(...)
    # SCARTA la colonna di raggruppamento ("agent") dal risultato quando la
    # funzione applicata ritorna un sottoinsieme delle stesse righe (es. .sample()).
    # Questo causava un KeyError piu' avanti nello script. Si usa quindi un
    # ciclo esplicito per gruppo, robusto su tutte le versioni di pandas.
    sampled_parts = []
    for agent_name, group in df.groupby("agent"):
        n = min(n_per_agent, len(group))
        sampled_parts.append(group.sample(n=n, random_state=seed))
    sampled = pd.concat(sampled_parts, ignore_index=True)

    # Join con metadati repo (licenza, linguaggio, stelle) - utile per IP rights.
    # 'license' e' confermata come colonna di repository: dopo il merge sara'
    # disponibile come 'repo_license' (es. valori come "MIT", "Apache-2.0"...).
    #
    # ATTENZIONE - DUE COLLISIONI DI NOMI RISCONTRATE CON DATI REALI:
    #   1. repository.id, con prefisso "repo_", diventerebbe "repo_id" - lo
    #      STESSO nome della chiave di join gia' presente in pull_request.
    #   2. repository.url, con prefisso "repo_", diventerebbe "repo_url" - ma
    #      pull_request ha GIA' una propria colonna "repo_url" (con valori
    #      equivalenti, e' l'URL della stessa repo). Pandas in questo caso
    #      rinomina entrambe in "repo_url_x"/"repo_url_y" invece di sollevare
    #      un errore, il che ha causato un KeyError piu' avanti nello script
    #      (02_fetch_files.py si aspettava "repo_url" senza suffisso).
    # Soluzione robusta: selezionare ESPLICITAMENTE solo le colonne di
    # repository che servono (non tutte con add_prefix), escludendo quelle
    # che duplicano informazioni gia' presenti in pull_request (id, url).
    repo_cols_needed = ["id", "license", "language", "stars", "forks"]
    repo_cols_available = [c for c in repo_cols_needed if c in repo_df.columns]
    repo_df_subset = repo_df[repo_cols_available].rename(columns={"id": "_repo_join_key"})
    repo_df_subset = repo_df_subset.rename(
        columns={c: f"repo_{c}" for c in repo_cols_available if c != "id"}
    )
    if "repo_id" in sampled.columns:
        sampled = sampled.merge(
            repo_df_subset,
            left_on="repo_id",
            right_on="_repo_join_key",
            how="left",
        ).drop(columns=["_repo_join_key"])

    # Filtra pr_commits solo per le PR selezionate, poi usa gli sha per
    # recuperare le righe corrispondenti in pr_commit_details (che contiene
    # filename, status, patch - il dettaglio file-per-file di ogni commit).
    selected_ids = set(sampled["id"].unique())
    relevant_commits = pr_commits_df[pr_commits_df["pr_id"].isin(selected_ids)]
    relevant_shas = set(relevant_commits["sha"].unique())

    commits_subset = commit_details_df[commit_details_df["sha"].isin(relevant_shas)]

    # Se pr_commit_details ha gia' una colonna pr_id propria e risulta
    # popolata correttamente, questo controllo lo segnala: in tal caso si
    # potrebbe semplificare il filtro usando direttamente pr_id invece del
    # passaggio per gli sha. Da verificare con i dati reali.
    if "pr_id" in commit_details_df.columns:
        direct_match = commit_details_df[commit_details_df["pr_id"].isin(selected_ids)]
        if len(direct_match) != len(commits_subset):
            print(
                f"⚠️ Attenzione: il filtro via sha ({len(commits_subset)} righe) e il "
                f"filtro via pr_id diretto ({len(direct_match)} righe) danno risultati "
                "diversi. Verificare manualmente quale e' corretto prima di procedere."
            )

    return sampled, commits_subset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Costruisce il subset AIDev per l'esperimento")
    parser.add_argument(
        "--agents",
        nargs="+",
        default=None,
        help="Lista di agenti da includere, valori esatti come compaiono nella "
             "colonna 'agent' (es. 'Claude Code', 'OpenAI Codex', 'Devin', "
             "'GitHub Copilot', 'Cursor' - VERIFICARE i valori esatti con "
             "00_explore_dataset.py prima di lanciare, perche' spazi/maiuscole/"
             "underscore possono variare). Se omesso, includi tutti gli agenti presenti.",
    )
    parser.add_argument("--n-per-agent", type=int, default=50, help="PR da campionare per agente")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", default=str(PROJECT_ROOT / "results" / "subset"))
    args = parser.parse_args()

    print("Carico AIDev-pop...")
    pr_df, repo_df, pr_commits_df, commit_details_df = load_aidev_pop()

    print("Agenti disponibili nel dataset:", pr_df["agent"].unique())

    agents = args.agents if args.agents else list(pr_df["agent"].unique())

    subset_pr, subset_commits = build_subset(
        pr_df, repo_df, pr_commits_df, commit_details_df,
        agents=agents,
        n_per_agent=args.n_per_agent,
        seed=args.seed,
    )

    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    subset_pr.to_parquet(f"{args.out_dir}/subset_pull_requests.parquet")
    subset_commits.to_parquet(f"{args.out_dir}/subset_commit_details.parquet")

    print(f"Subset creato: {len(subset_pr)} PR, {len(subset_commits)} record di commit/patch")
    print(subset_pr["agent"].value_counts())
