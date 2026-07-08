"""
analyze_fail.py — Analizza le estensioni dei file NON recuperati (after_fetched=False)
per capire quanti erano codice sorgente vero (analizzabile da Lizard) vs
file di config/documentazione (irrilevanti per le metriche di complessita').
"""
import pandas as pd

fetch = pd.read_csv("results/fetch_log.csv")

# Un file "fallito" e' uno che doveva avere una versione after ma non e' stato recuperato.
# (n/a_removed = file rimossi dalla PR, per cui l'after non esiste per definizione: esclusi)
fetch["fail"] = fetch["after_fetched"].astype(str) == "False"
failed = fetch[fetch["fail"]].copy()

# Estensione (minuscola) dell'ultimo pezzo del path
failed["ext"] = failed["path"].astype(str).str.extract(r"(\.[a-zA-Z0-9]+)$")[0].str.lower()

# Estensioni che Lizard analizza come codice sorgente
CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".c", ".cpp", ".cc",
    ".h", ".hpp", ".cs", ".rb", ".php", ".rs", ".swift", ".kt", ".scala",
    ".m", ".mm", ".lua", ".r", ".sh", ".pl",
}
failed["is_code"] = failed["ext"].isin(CODE_EXT)

n_fail = len(failed)
n_code = int(failed["is_code"].sum())
n_other = n_fail - n_code
tot_ok = int((fetch["after_fetched"].astype(str) == "True").sum())

print(f"Totale file falliti (after non recuperato): {n_fail}")
print()
print("=== Codice sorgente vs altro ===")
print(f"File di CODICE falliti:    {n_code:4}  ({n_code/n_fail*100:.1f}% dei falliti)")
print(f"File NON-codice falliti:   {n_other:4}  ({n_other/n_fail*100:.1f}% dei falliti)")
print()
print("=== Top 15 estensioni tra i file falliti ===")
print(failed["ext"].value_counts().head(15).to_string())
print()
print("=== Impatto reale sulle metriche di complessita' (Lizard) ===")
print(f"File di codice persi: {n_code}")
print(f"File recuperati con successo: {tot_ok}")
print(f"Perdita sul codice analizzabile: {n_code/tot_ok*100:.2f}%")