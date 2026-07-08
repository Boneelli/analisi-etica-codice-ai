"""
genera_report.py — Report completo dei risultati misurati per l'esperimento.

USO:
    python genera_report.py

Legge da results/ e scrive results/REPORT_completo.txt (e alcuni CSV riassuntivi).
Robusto ai file mancanti: se un file non c'e', salta quella sezione con un avviso.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# Percorso della cartella results calcolato in modo ASSOLUTO a partire dalla
# posizione di questo file (scripts/analyze/genera_report.py): due .parent
# risalgono da analyze/ a scripts/ a tesi-setup/ (la root del progetto). Cosi'
# lo script funziona da qualsiasi cartella lo si lanci, non solo dalla root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = PROJECT_ROOT / "results"
SUBSET = RESULTS / "subset"
SUSTAINABILITY = RESULTS / "sustainability"
SUBJECT_RIGHTS = RESULTS / "subject_rights"
IP_RIGHTS = RESULTS / "ip_rights"
FAIRNESS = RESULTS / "fairness"
REPORT = RESULTS / "report"
REPORT.mkdir(parents=True, exist_ok=True)
OUT_TXT = REPORT / "REPORT_completo.txt"

AGENTS = ["Claude_Code", "Copilot", "Cursor", "Devin", "OpenAI_Codex"]

# Soglie green smell (coerenti con configs/green_smells_thresholds.json)
CCN_HIGH = 10
NLOC_LONG = 50
PARAMS_MANY = 5

CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".c", ".cpp", ".cc",
    ".h", ".hpp", ".cs", ".rb", ".php", ".rs", ".swift", ".kt", ".scala",
    ".m", ".mm", ".lua", ".r", ".sh", ".pl",
}

# Buffer per accumulare il testo del report e stamparlo + salvarlo
_lines = []
def out(s=""):
    print(s)
    _lines.append(str(s))

def header(title):
    out()
    out("=" * 72)
    out(title)
    out("=" * 72)

def safe_read_csv(path):
    try:
        df = pd.read_csv(path)
        return df if len(df) > 0 else None
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return None


def get_pr_agent_map():
    """Costruisce il mapping pr_id -> agent. Preferisce il parquet del subset
    (completo, tutte le 250 PR); se non leggibile, ricade sui CSV che hanno
    gia' la colonna agent (copre solo le PR con metriche)."""
    try:
        pr = pd.read_parquet(SUBSET / "subset_pull_requests.parquet")
        return pr.set_index("id")["agent"].to_dict(), "parquet (completo, 250 PR)"
    except Exception:
        m = {}
        for p in [SUSTAINABILITY / "lizard_metrics.csv",
                  SUSTAINABILITY / "green_smell_density.csv",
                  SUBJECT_RIGHTS / "gitleaks_summary.csv"]:
            d = safe_read_csv(p)
            if d is not None and "pr_id" in d.columns and "agent" in d.columns:
                m.update(d[["pr_id", "agent"]].drop_duplicates().set_index("pr_id")["agent"].to_dict())
        return m, "CSV parziale (solo PR con metriche)"


def fmt_table(df):
    """Formatta un DataFrame come tabella testuale leggibile."""
    return df.to_string()


# ======================================================================
out(f"REPORT RISULTATI ESPERIMENTO")

pr2agent, map_source = get_pr_agent_map()
out(f"\nMapping PR->agente: {map_source} — {len(pr2agent)} PR mappate")


# ----------------------------------------------------------------------
# BASE DI NORMALIZZAZIONE
# ----------------------------------------------------------------------
header("BASE DI NORMALIZZAZIONE (quantita' di codice per agente)")

lz = safe_read_csv(SUSTAINABILITY / "lizard_metrics.csv")
if lz is not None:
    funcs_per_agent = lz.groupby("agent").size().reindex(AGENTS)
    files_per_agent = lz.groupby("agent")["file"].nunique().reindex(AGENTS)
    base = pd.DataFrame({
        "n_funzioni": funcs_per_agent,
        "n_file_distinti": files_per_agent,
    })
    out(fmt_table(base))
    out()
    out("NOTA: lo sbilanciamento e' forte (Claude_Code ha ~10x le funzioni di")
    out("Codex). Le metriche seguenti sono NORMALIZZATE per permettere un")
    out("confronto equo tra agenti che producono quantita' di codice diverse.")
else:
    funcs_per_agent = None
    out("[!] lizard_metrics.csv assente: salto la base di normalizzazione.")


# ----------------------------------------------------------------------
# 1. SUSTAINABILITY
# ----------------------------------------------------------------------
header("1. SUSTAINABILITY (Lizard)")

if lz is not None:
    lz["high_ccn"] = lz["ccn"] > CCN_HIGH
    lz["long_method"] = lz["nloc"] > NLOC_LONG
    lz["many_params"] = lz["parameter_count"] > PARAMS_MANY

    out("\n--- Complessita' ciclomatica (CCN) per funzione ---")
    ccn = lz.groupby("agent")["ccn"].agg(
        media="mean", mediana="median",
        p90=lambda x: x.quantile(0.90), max="max", n="count"
    ).reindex(AGENTS).round(2)
    out(fmt_table(ccn))

    # test robustezza: media troncata al 95° percentile
    out("\n--- Test robustezza: CCN media escludendo il 5% piu' complesso ---")
    rob = {}
    for a in AGENTS:
        s = lz[lz["agent"] == a]["ccn"]
        if len(s) > 0:
            rob[a] = [round(s.mean(), 2), round(s[s <= s.quantile(0.95)].mean(), 2)]
    rob_df = pd.DataFrame(rob, index=["media_completa", "media_troncata_95%"]).T
    out(fmt_table(rob_df))

    out("\n--- % funzioni 'smelly' per tipo di smell (NORMALIZZATO su n funzioni) ---")
    smell = pd.DataFrame({
        "perc_CCN_alto(>10)": (lz.groupby("agent")["high_ccn"].mean() * 100),
        "perc_long_method(>50nloc)": (lz.groupby("agent")["long_method"].mean() * 100),
        "perc_troppi_param(>5)": (lz.groupby("agent")["many_params"].mean() * 100),
    }).reindex(AGENTS).round(2)
    out(fmt_table(smell))

    gs = safe_read_csv(SUSTAINABILITY / "green_smell_density.csv")
    if gs is not None:
        out("\n--- Green Smell Density (per PR) ---")
        gsd = gs.groupby("agent")["green_smell_density"].agg(
            media="mean", mediana="median", dev_std="std", n_PR="count"
        ).reindex(AGENTS).round(3)
        out(fmt_table(gsd))
        out("\nNOTA: la media puo' essere alzata da poche PR con density molto")
        out("alta; confrontare sempre con la mediana. Le metriche per-funzione")
        out("(CCN, %smell) sono piu' robuste di questa per-PR.")
else:
    gs = None
    out("[!] lizard_metrics.csv assente: sezione Sustainability saltata.")


# ----------------------------------------------------------------------
# 2. SUBJECT RIGHTS
# ----------------------------------------------------------------------
header("2. SUBJECT RIGHTS — Data Leakage (Gitleaks)")

try:
    gl = pd.read_json(SUBJECT_RIGHTS / "gitleaks_findings.jsonl", lines=True)
    if len(gl) == 0:
        gl = None
except (FileNotFoundError, ValueError):
    gl = None

if gl is not None:
    if "agent" not in gl.columns:
        gl["agent"] = gl["pr_id"].map(pr2agent)

    out(f"\nTotale finding: {len(gl)} su {gl['pr_id'].nunique()} PR distinte")
    out("\n--- Finding grezzi per agente ---")
    grezzi = gl["agent"].value_counts().reindex(AGENTS).fillna(0).astype(int)
    out(grezzi.to_string())

    out("\n--- Tipi di secret rilevati ---")
    out(gl["RuleID"].value_counts().to_string())

    if funcs_per_agent is not None:
        out("\n--- Leak NORMALIZZATI per 1000 funzioni analizzate ---")
        norm = pd.DataFrame({
            "leak_grezzi": grezzi,
            "n_funzioni": funcs_per_agent,
            "leak_per_1000_funz": (grezzi / funcs_per_agent * 1000).round(3),
        })
        out(fmt_table(norm))
        out("\nNOTA: la normalizzazione puo' ribaltare la classifica grezza —")
        out("un agente con molti leak assoluti ma tanto codice puo' risultare")
        out("piu' 'pulito' per unita' di codice di uno con pochi leak ma poco codice.")

    # --- Integrazione della VALIDAZIONE MANUALE, se disponibile ---
    valid = safe_read_csv(SUBJECT_RIGHTS / "gitleaks_validazione.csv")
    validato = (
            valid is not None
            and "categoria_finale" in valid.columns
            and valid["categoria_finale"].notna().any()
            and (valid["categoria_finale"].astype(str).str.strip() != "").any()
    )

    if validato:
        v = valid.copy()
        v["categoria_finale"] = v["categoria_finale"].astype(str).str.strip()
        v = v[v["categoria_finale"] != ""]

        # Deduplica per segreto univoco (un secret_group = un segreto reale)
        dedup = v.drop_duplicates("secret_group")
        n_univoci = dedup["secret_group"].nunique()
        n_grezzi = len(gl)

        out("\n" + "-" * 60)
        out("VALIDAZIONE (deduplicazione + controllo manuale)")
        out("-" * 60)
        out(f"\nFinding grezzi: {n_grezzi}  ->  segreti univoci: {n_univoci} "
            f"({n_grezzi - n_univoci} erano duplicati)")

        # categorie: VP = vero positivo, tutto il resto = falso positivo
        VP_LABELS = {"VP", "vero_positivo", "vp"}
        dedup["is_vp"] = dedup["categoria_finale"].isin(VP_LABELS)
        n_vp = int(dedup["is_vp"].sum())
        n_fp = n_univoci - n_vp

        out("\n--- Esito per categoria (su segreti univoci) ---")
        out(dedup["categoria_finale"].value_counts().to_string())

        out(f"\n>>> VERI POSITIVI (leak reali): {n_vp}")
        out(f">>> Falsi positivi:             {n_fp}  su {n_univoci} segreti univoci")

        if n_vp == 0:
            out("\nRISULTATO: nessun leak reale di produzione nel campione.")
            out("Tutti i finding grezzi si sono rivelati falsi positivi")
            out("(placeholder, fixtures di test, checksum di dipendenze,")
            out("valori pubblici noti, chiavi di sviluppo/CI).")
        else:
            out("\n--- Veri positivi per agente ---")
            vp_rows = dedup[dedup["is_vp"]]
            vp_rows = vp_rows.copy()
            if "agent" not in vp_rows.columns:
                vp_rows["agent"] = vp_rows["pr_id"].map(pr2agent)
            out(vp_rows["agent"].value_counts().to_string())

        out("\nNOTA METODOLOGICA: il conteggio grezzo (23 finding) avrebbe")
        out("suggerito differenze tra agenti; la validazione mostra che il")
        out("dato reale e' azzerato dai falsi positivi. Illustra perche' i")
        out("risultati automatici di Gitleaks vanno sempre validati a mano.")
    else:
        out("\n[CAUTELE] Finding NON ancora validati: includono falsi positivi")
        out("(chiavi di test, placeholder, checksum). Compila la colonna")
        out("'categoria_finale' in results/gitleaks_validazione.csv e rilancia")
        out("per ottenere l'esito validato. (Genera il foglio con valida_gitleaks.py)")
else:
    out("\nNessun finding Gitleaks (o file assente).")


# ----------------------------------------------------------------------
# 3. IP RIGHTS
# ----------------------------------------------------------------------
header("3. IP RIGHTS (ScanCode)")

conf = safe_read_csv(IP_RIGHTS / "license_conflicts.csv")
strip = safe_read_csv(IP_RIGHTS / "copyright_stripping.csv")

n_conf = 0 if conf is None else len(conf)
n_strip = 0 if strip is None else len(strip)

out(f"\nConflitti di licenza: {n_conf}")
out(f"Casi di copyright stripping: {n_strip}")

if n_conf > 0 and conf is not None and "agent" in conf.columns:
    out("\n--- Conflitti per agente ---")
    out(conf["agent"].value_counts().to_string())
if n_conf == 0:
    out("\nNOTA: 0 conflitti e' il risultato atteso dopo il filtro sui file di")
    out("lock auto-generati (package-lock.json, ecc.) che generavano falsi")
    out("positivi. La tabella di compatibilita' licenze e' pero' semplificata:")
    out("una matrice SPDX completa potrebbe rilevare casi non catturati.")


# ----------------------------------------------------------------------
# 4. FAIRNESS (LLM-as-judge)
# ----------------------------------------------------------------------
header("4. FAIRNESS (LLM-as-judge)")

judge = safe_read_csv(FAIRNESS / "llm_judge_fairness.csv")
if judge is not None:
    SCORE_COLS = ["score_demographic_fairness", "score_accessibility_inclusion",
                  "score_inclusive_language", "score_overall_ethics"]
    n_val = len(judge)
    n_err = int(judge["parse_error"].sum()) if "parse_error" in judge.columns else 0
    out(f"\nPR valutate: {n_val} | errori di parsing: {n_err}")

    # Distribuzione dei punteggi overall (la piu' informativa)
    out("\n--- Distribuzione punteggio 'overall_ethics' ---")
    out(judge["score_overall_ethics"].value_counts().sort_index().to_string())

    # Casi NON neutri (almeno un punteggio != 3). NIENTE medie per agente:
    # con quasi tutte le PR neutre (=3), le medie sarebbero schiacciate su 3.0
    # e differenze minime tra agenti (dovute a 1-2 casi isolati) apparirebbero
    # come pattern sistematici inesistenti. Si riporta invece il CONTEGGIO
    # assoluto dei casi non-neutri, piu' onesto.
    mask_nn = (judge[SCORE_COLS] != 3).any(axis=1)
    non_neutre = judge[mask_nn]
    out(f"\n--- PR con almeno un punteggio non-neutro (!=3): {len(non_neutre)} su {n_val} ---")
    out("Conteggio casi non-neutri per agente (NON medie - vedi nota):")
    # conteggio per agente, con gli agenti a 0 espliciti
    cnt = non_neutre["agent"].value_counts()
    for a in AGENTS:
        out(f"  {a:15} {int(cnt.get(a, 0))}")
    if len(non_neutre) > 0:
        out("\nDettaglio casi non-neutri:")
        out(non_neutre[["pr_id", "agent"] + SCORE_COLS].to_string(index=False))

    out("\nNOTA: NON si riportano le medie dei punteggi per agente. Con "
        f"{n_val - len(non_neutre)} PR su {n_val} a valore neutro (3), le medie "
        "sarebbero tutte ~3.0 e le differenze (dovute a 1-2 casi isolati su 50 "
        "PR per agente) NON sarebbero statisticamente significative: darebbero "
        "l'impressione fuorviante di un pattern sistematico tra agenti inesistente.")

    # --- Validazione manuale (accordo umano-judge), se disponibile ---
    confronto = safe_read_csv(FAIRNESS / "fairness_validazione_CONFRONTO.csv")
    if confronto is not None:
        out("\n" + "-" * 60)
        out("VALIDAZIONE MANUALE (accordo umano-judge)")
        out("-" * 60)
        dims = [("demographic_fairness", "mio_demographic_fairness", "judge_demographic_fairness"),
                ("accessibility_inclusion", "mio_accessibility_inclusion", "judge_accessibility_inclusion"),
                ("inclusive_language", "mio_inclusive_language", "judge_inclusive_language"),
                ("overall_ethics", "mio_overall_ethics", "judge_overall_ethics")]
        all_diff = []
        forti = []
        for nome, mc, jc in dims:
            if mc in confronto.columns and jc in confronto.columns:
                sub = confronto[[mc, jc]].dropna()
                d = (sub[mc].astype(float) - sub[jc].astype(float)).abs()
                all_diff.extend(d.tolist())
                for idx, val in d.items():
                    if val >= 2:
                        forti.append((confronto.loc[idx, "pr_id"], confronto.loc[idx, "agent"], nome,
                                      confronto.loc[idx, mc], confronto.loc[idx, jc]))
        if all_diff:
            import numpy as _np
            arr = _np.array(all_diff)
            out(f"\nPR validate a mano: {len(confronto)}")
            out(f"Accordo esatto:     {(arr == 0).mean()*100:.1f}%")
            out(f"Accordo entro +/-1: {(arr <= 1).mean()*100:.1f}%")
            out(f"Differenza media assoluta: {arr.mean():.2f}")
            if forti:
                out("\nNOTA: un disaccordo sulla dimensione accessibilita' puo'")
                out("derivare dal troncamento del diff (il judge vede solo parte")
                out("del changeset). Il giudizio umano, sul diff completo, e' piu'")
                out("accurato. Verificare questi casi a mano.")
                out("\nL'accordo elevato valida l'affidabilita' del judge; i")
                out("disaccordi documentano la necessita' della verifica umana.")
            else:
                out("\nNessun disaccordo forte (differenza >= 2): l'accordo tra")
                out("giudizio umano e automatico e' pieno. Questo valida")
                out("l'affidabilita' del judge sul dataset finale.")
    else:
        out("\n[La validazione manuale non e' ancora disponibile: genera e compila")
        out(" fairness_validazione_CIECO.csv, poi lancia confronta_validazione.py]")
else:
    out("\n[!] llm_judge_fairness.csv assente: sezione Fairness saltata.")


# ----------------------------------------------------------------------
# 5. COPERTURA E RECUPERO FILE
# ----------------------------------------------------------------------
header("5. COPERTURA E RECUPERO FILE")

fetch = safe_read_csv(SUBSET / "fetch_log.csv")
if fetch is not None:
    fetch["ok"] = fetch["after_fetched"].astype(str) == "True"
    fetch["fail"] = fetch["after_fetched"].astype(str) == "False"
    n_ok = int(fetch["ok"].sum())
    n_fail = int(fetch["fail"].sum())
    n_removed = int((fetch["after_fetched"].astype(str) == "n/a_removed").sum())
    tot = len(fetch)
    out(f"\nFile totali attesi: {tot}")
    out(f"  recuperati (after=True): {n_ok} ({n_ok/tot*100:.1f}%)")
    out(f"  falliti (after=False):   {n_fail} ({n_fail/tot*100:.1f}%)")
    out(f"  rimossi (n/a_removed):   {n_removed} ({n_removed/tot*100:.1f}%)")

    # Impatto sul codice analizzabile
    failed = fetch[fetch["fail"]].copy()
    failed["ext"] = failed["path"].astype(str).str.extract(r"(\.[a-zA-Z0-9]+)$")[0].str.lower()
    failed["is_code"] = failed["ext"].isin(CODE_EXT)
    n_code_fail = int(failed["is_code"].sum())
    out(f"\n--- Impatto reale sulle metriche di complessita' ---")
    out(f"Dei {n_fail} file falliti, solo {n_code_fail} ({n_code_fail/n_fail*100:.1f}%) erano CODICE.")
    out(f"Perdita sul codice analizzabile: {n_code_fail}/{n_ok} = {n_code_fail/n_ok*100:.2f}%")
    out("(Il resto erano config/documentazione, che Lizard non analizza:")
    out(" il loro mancato recupero non impatta le metriche di complessita'.)")

    # Recupero per agente
    if "agent" not in fetch.columns:
        fetch["agent"] = fetch["pr_id"].map(pr2agent)
    if fetch["agent"].notna().any():
        out("\n--- Tasso di fallimento file per agente (%) ---")
        fr = (fetch.groupby("agent")["fail"].mean() * 100).reindex(AGENTS).round(2)
        out(fr.to_string())
        out("\n--- Copertura PR: PR con almeno un file recuperato, per agente ---")
        cov = fetch[fetch["ok"]].groupby("agent")["pr_id"].nunique().reindex(AGENTS)
        out(cov.to_string())
        out("\nNOTA METODOLOGICA: 'PR completamente recuperata' NON e' una buona")
        out("metrica di confronto — dipende dal numero di file per PR piu' che")
        out("dalla qualita' del recupero (una PR con 1 solo file mancante su 20")
        out("risulta 'parziale'). Usare il tasso di fallimento file e la")
        out("copertura per PR (almeno un file), non la % di PR complete.")
else:
    out("[!] fetch_log.csv assente: sezione recupero file saltata.")


# ----------------------------------------------------------------------
# SINTESI
# ----------------------------------------------------------------------
header("SINTESI E LIMITI")
out("""
RISULTATI PER DIMENSIONE:
- Sustainability (Lizard): segnale piu' solido. OpenAI Codex produce il codice
  piu' complesso per unita' prodotta (CCN mediana doppia, robusto agli outlier),
  coerente con Dou et al. (2026). Quadro non monodimensionale (Devin sui long
  method, Copilot sui parametri).
- Subject Rights (Gitleaks): 23 finding grezzi -> 0 veri leak dopo validazione
  manuale (tutti falsi positivi: placeholder, fixtures di test, checksum go.sum,
  valori pubblici noti, chiavi dev/CI).
- IP Rights (ScanCode): 0 conflitti, 0 copyright stripping dopo il filtro sui
  file di lock auto-generati.
- Fairness (LLM-judge): 250 PR valutate, ~0% errori di parsing. Pochi casi non
  neutri (4 su 250), tutti sulla dimensione accessibilita' e prevalentemente
  sull'agente che produce le UI piu' estese. Validazione manuale su 25 PR: 98%
  di accordo esatto umano-judge, 100% entro +/-1, nessun disaccordo forte.

LIMITI DA DICHIARARE:
- Gitleaks (Subject Rights) e Fairness lavorano sui DIFF, non sui file scaricati:
  immuni al problema del recupero file. Lizard/ScanCode usano i file: perdita
  effettiva sul codice ~5%, distribuita e trascurabile.
- Fairness: il diff inviato al judge e' troncato a 100.000 caratteri (~16% delle
  PR, quelle genuinamente enormi, resta troncato: limite intrinseco). Un limite
  precedente piu' basso (10k) distorceva alcuni giudizi su PR grandi; alzandolo
  il problema e' stato in larga parte risolto. I casi non-neutri sono comunque
  verificati a mano.
- Numeri assoluti piccoli per Gitleaks/ScanCode/eventi Fairness: differenze
  indicative, non prove statistiche forti.
- Tabella compatibilita' licenze semplificata: da sostituire con matrice SPDX.
- Metodologicamente: 2 dimensioni su 4 (Subject Rights, IP Rights) hanno prodotto
  risultati grezzi ingannevoli (23 falsi leak, 41 falsi conflitti) azzerati solo
  dopo validazione/filtraggio. Il controllo umano sui risultati automatici e' un
  contributo metodologico centrale della tesi.
""")

# ----------------------------------------------------------------------
# Salvataggio
# ----------------------------------------------------------------------
OUT_TXT.write_text("\n".join(_lines), encoding="utf-8")

# CSV riassuntivo per agente (se possibile)
if lz is not None and funcs_per_agent is not None:
    summary = pd.DataFrame({"n_funzioni": funcs_per_agent})
    summary["ccn_media"] = lz.groupby("agent")["ccn"].mean().round(2)
    summary["ccn_mediana"] = lz.groupby("agent")["ccn"].median()
    summary["perc_high_ccn"] = (lz.groupby("agent")["high_ccn"].mean() * 100).round(2)
    summary["perc_long_method"] = (lz.groupby("agent")["long_method"].mean() * 100).round(2)
    summary["perc_many_params"] = (lz.groupby("agent")["many_params"].mean() * 100).round(2)
    if gs is not None:
        summary["green_smell_density"] = gs.groupby("agent")["green_smell_density"].mean().round(3)
    if gl is not None:
        grezzi = gl["agent"].value_counts().reindex(AGENTS).fillna(0).astype(int)
        summary["leak_grezzi"] = grezzi
        summary["leak_per_1000_funz"] = (grezzi / funcs_per_agent * 1000).round(3)
    summary = summary.reindex(AGENTS)
    summary.to_csv(REPORT / "riepilogo_per_agente.csv")
    out(f"\n[Salvato] {REPORT / 'riepilogo_per_agente.csv'}")

out(f"[Salvato] {OUT_TXT}")