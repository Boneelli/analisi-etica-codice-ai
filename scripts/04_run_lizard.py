"""
04_run_lizard.py

Misura, per ogni PR del subset:
  1. Complessita' Ciclomatica (CCN) tramite Lizard, sui file/funzioni
     modificati dalla PR.
  2. Green Smell Density: Si costruisce
     come rapporto tra "unita' di codice (funzioni) che violano soglie
     associate a code smell ad alto consumo energetico" e il totale delle
     funzioni analizzate. Le soglie sono parametri di configurazione (vedi
     configs/green_smells_thresholds.json).

Installazione:
    pip install lizard --break-system-packages

Uso:
    python lizard --csv <file_o_cartella>   # CLI
    oppure, come qui, tramite l'API python: import lizard; lizard.analyze_file(...)

Output: results/lizard_metrics.csv (una riga per funzione)
        results/green_smell_density.csv (una riga per PR/file)
"""

import lizard
import pandas as pd
import json
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
SUBSET_DIR = RESULTS_DIR / "subset"
SUSTAINABILITY_DIR = RESULTS_DIR / "sustainability"
CONFIGS_DIR = PROJECT_ROOT / "configs"


def load_thresholds() -> dict:
    with open(CONFIGS_DIR / "green_smells_thresholds.json", encoding="utf-8") as f:
        return json.load(f)


def analyze_file(filepath: str, pr_id, agent: str) -> list[dict]:
    """Analizza un singolo file con Lizard e ritorna una riga per funzione."""
    rows = []
    try:
        result = lizard.analyze_file(filepath)
    except Exception as e:
        log.warning(f"Lizard fallito su {filepath}: {e}")
        return rows

    for func in result.function_list:
        rows.append({
            "pr_id": pr_id,
            "agent": agent,
            "file": filepath,
            "function_name": func.name,
            "ccn": func.cyclomatic_complexity,
            "nloc": func.nloc,                  # lines of code (no comments/blank)
            "token_count": func.token_count,
            "parameter_count": len(func.parameters),
            "max_nesting_depth": getattr(func, "top_nesting_level", None),
            "long_name": func.long_name,
        })
    return rows


def classify_green_smells(func_row: dict, thresholds: dict) -> list[str]:
    """
    Applica soglie configurabili per etichettare una funzione con uno o piu'
    "green code smell" (proxy di inefficienza/consumo energetico).
    """
    smells = []
    if func_row["ccn"] > thresholds["high_ccn"]:
        smells.append("high_cyclomatic_complexity")
    if func_row["nloc"] > thresholds["long_method_nloc"]:
        smells.append("long_method")
    if func_row["parameter_count"] > thresholds["too_many_parameters"]:
        smells.append("long_parameter_list")
    if func_row.get("max_nesting_depth") and func_row["max_nesting_depth"] > thresholds["deep_nesting"]:
        smells.append("deep_nesting")
    return smells


def main():
    subset_pr = pd.read_parquet(SUBSET_DIR / "subset_pull_requests.parquet")
    thresholds = load_thresholds()

    all_function_rows = []

    for _, pr in subset_pr.iterrows():
        # Si analizzano i file scaricati da 02_fetch_files.py, versione
        # "after" (post-merge), gia' filtrati ai soli file toccati dalla PR.
        # Questo e' preferibile al repo intero: la metrica e' attribuibile
        # all'agente, non a codice preesistente non toccato dalla PR.
        files_dir = PROJECT_ROOT / "data" / "files" / str(pr["id"]) / "after"
        if not files_dir.exists():
            continue

        source_files = [str(p) for p in files_dir.iterdir() if p.is_file()]
        # I file sono salvati da 02_fetch_files.py con safe_path(), che
        # preserva l'estensione originale in coda (es. "..._a1b2c3d4.py"),
        # quindi Lizard riconosce correttamente il linguaggio.

        for f in source_files:
            rows = analyze_file(f, pr["id"], pr["agent"])
            all_function_rows.extend(rows)

    func_df = pd.DataFrame(all_function_rows)
    SUSTAINABILITY_DIR.mkdir(parents=True, exist_ok=True)
    func_df.to_csv(SUSTAINABILITY_DIR / "lizard_metrics.csv", index=False)

    if func_df.empty:
        log.info("Nessuna funzione analizzata. Controllare i path dei repo checkoutati.")
        return

    func_df["smells"] = func_df.apply(lambda r: classify_green_smells(r, thresholds), axis=1)
    func_df["n_smells"] = func_df["smells"].apply(len)

    # Green Smell Density per PR = funzioni con >=1 smell / funzioni totali
    density = (
        func_df.groupby("pr_id")
        .agg(
            n_functions=("function_name", "count"),
            n_functions_with_smell=("n_smells", lambda x: (x > 0).sum()),
            avg_ccn=("ccn", "mean"),
            max_ccn=("ccn", "max"),
        )
        .reset_index()
    )
    density["green_smell_density"] = density["n_functions_with_smell"] / density["n_functions"]
    density = density.merge(subset_pr[["id", "agent"]], left_on="pr_id", right_on="id", how="left")

    density.to_csv(SUSTAINABILITY_DIR / "green_smell_density.csv", index=False)
    log.info(f"Calcolata densita' di green smell per {len(density)} PR")


if __name__ == "__main__":
    main()
