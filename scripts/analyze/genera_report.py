"""
genera_report.py — Report completo dei risultati misurati per l'esperimento.

USO:
    python genera_report.py

Legge da results/ e scrive results/report/REPORT_completo.txt (e alcuni CSV riassuntivi).
Robusto ai file mancanti: se un file non c'e', salta quella sezione con un avviso.
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# Su Windows la console usa cp1252 e va in errore sui caratteri Unicode
# (emoji, trattini tipografici) che possono comparire nei testi del judge.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

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
    (completo, tutte le PR del campione); se non leggibile, ricade sui CSV che
    hanno gia' la colonna agent (copre solo le PR con metriche)."""
    try:
        pr = pd.read_parquet(SUBSET / "subset_pull_requests.parquet")
        return pr.set_index("id")["agent"].to_dict(), f"parquet (completo, {len(pr)} PR)"
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
    out("NOTA: lo sbilanciamento e' forte. Le metriche seguenti sono")
    out("NORMALIZZATE per permettere un confronto equo tra agenti che")
    out("producono quantita' di codice diverse.")
    out()
    out("Le metriche escludono il codice NON scritto dall'agente (dipendenze")
    out("vendorizzate, codice generato da tool, bundle di build): senza quel")
    out("filtro il 38% delle funzioni non sarebbe attribuibile agli agenti e")
    out("il confronto risulterebbe invertito.")
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
    out("\nNOTA: la mediana e' 1.0 per tutti gli agenti (la maggior parte delle")
    out("funzioni e' banale): il confronto va letto su media, 90esimo percentile")
    out("e percentuale di funzioni oltre soglia, non sulla mediana.")

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
        out("Questi sono comunque conteggi GREZZI: vedi la validazione sotto.")

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

        # Categorie: si distingue un leak PERSISTENTE (presente nello stato
        # finale della PR) da uno RIMEDIATO (introdotto e poi rimosso dallo
        # stesso agente nel corso della PR). Il secondo non espone piu' il
        # segreto nel codice consegnato, ma resta nella storia dei commit:
        # e' un caso reale, non un falso positivo, e va contato a parte.
        VP_LABELS = {"VP", "vero_positivo", "vp"}
        VP_RIMEDIATI = {"VP_Rimediato", "VP_rimediato", "vp_rimediato",
                        "VP-Rimediato", "VP-rimediato"}
        dedup = dedup.copy()
        dedup["is_vp"] = dedup["categoria_finale"].isin(VP_LABELS)
        dedup["is_vp_rim"] = dedup["categoria_finale"].isin(VP_RIMEDIATI)
        n_vp = int(dedup["is_vp"].sum())
        n_vp_rim = int(dedup["is_vp_rim"].sum())
        n_fp = n_univoci - n_vp - n_vp_rim

        out("\n--- Esito per categoria (su segreti univoci) ---")
        out(dedup["categoria_finale"].value_counts().to_string())

        out(f"\n>>> LEAK PERSISTENTI (presenti nel codice finale): {n_vp}")
        out(f">>> Leak RIMEDIATI nella stessa PR:                {n_vp_rim}")
        out(f">>> Falsi positivi:                                {n_fp}  su {n_univoci} segreti univoci")

        if n_vp == 0 and n_vp_rim == 0:
            out("\nRISULTATO: nessun leak reale nel campione. Tutti i finding")
            out("grezzi si sono rivelati falsi positivi (placeholder, fixtures")
            out("di test, checksum di dipendenze, valori pubblici noti, chiavi")
            out("di sviluppo/CI).")
        elif n_vp == 0:
            out("\nRISULTATO: nessun leak persistente nel codice consegnato.")
            out(f"Si registra pero' {n_vp_rim} caso di credenziale reale introdotta")
            out("e poi rimossa dall'agente nel corso della stessa PR: lo stato")
            out("finale e' pulito, ma il segreto resta nella storia dei commit")
            out("(la prassi di sicurezza richiederebbe la rotazione della chiave,")
            out("non la sola rimozione). Tutti gli altri finding sono falsi")
            out("positivi (placeholder, fixtures di test, checksum di dipendenze,")
            out("valori pubblici noti, chiavi di sviluppo/CI).")
            rim = dedup[dedup["is_vp_rim"]].copy()
            if "agent" not in rim.columns:
                rim["agent"] = rim["pr_id"].map(pr2agent)
            out("\n--- Casi rimediati ---")
            cols_rim = [c for c in ["pr_id", "agent", "RuleID", "note"] if c in rim.columns]
            out(rim[cols_rim].to_string(index=False))
        else:
            out("\n--- Leak persistenti per agente ---")
            vp_rows = dedup[dedup["is_vp"]].copy()
            if "agent" not in vp_rows.columns:
                vp_rows["agent"] = vp_rows["pr_id"].map(pr2agent)
            out(vp_rows["agent"].value_counts().to_string())

        out("\nNOTA METODOLOGICA: il conteggio grezzo (98 finding) avrebbe")
        out("suggerito differenze marcate tra agenti; la deduplicazione e la")
        out("validazione manuale mostrano che quasi tutto e' rumore. Illustra")
        out("perche' i risultati automatici di Gitleaks vanno sempre validati.")
    else:
        out("\n[CAUTELE] Finding NON ancora validati: includono falsi positivi")
        out("(chiavi di test, placeholder, checksum). Compila la colonna")
        out("'categoria_finale' in results/subject_rights/gitleaks_validazione.csv")
        out("e rilancia per ottenere l'esito validato.")
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
    out("\nNOTA: 0 conflitti e' il risultato ottenuto dopo due correzioni:")
    out("l'esclusione dei file di lock auto-generati (package-lock.json, ecc.),")
    out("che elencano le licenze di tutte le dipendenze transitive, e la")
    out("rimozione dalla tabella di coppie non realmente incompatibili")
    out("(una licenza permissiva puo' stare in un progetto copyleft).")
    out("La tabella di compatibilita' resta pero' semplificata: una matrice")
    out("SPDX completa potrebbe rilevare casi qui non catturati.")


# ----------------------------------------------------------------------
# 4. FAIRNESS (LLM-as-judge)
# ----------------------------------------------------------------------
header("4. FAIRNESS (LLM-as-judge)")

judge = safe_read_csv(FAIRNESS / "llm_judge_fairness.csv")
if judge is not None:
    SCORE_COLS = ["score_demographic_fairness", "score_accessibility_inclusion",
                  "score_inclusive_language", "score_overall_ethics"]
    # Le tre dimensioni SOSTANZIALI. 'overall_ethics' e' una sintesi prodotta
    # dal modello e non e' vincolata alle altre tre: la validazione manuale ha
    # mostrato che il judge le assegna valori non neutri anche quando tutte le
    # dimensioni sostanziali sono neutre. Non entra quindi nella definizione di
    # "evento", ma viene riportata a parte come controllo.
    DIM_SOSTANZIALI = SCORE_COLS[:3]

    n_val = len(judge)
    n_err = int(judge["parse_error"].sum()) if "parse_error" in judge.columns else 0
    out(f"\nPR valutate: {n_val} | errori di parsing: {n_err}")

    out("\n--- Distribuzione punteggio 'overall_ethics' ---")
    out(judge["score_overall_ethics"].value_counts().sort_index().to_string())

    mask_eventi = (judge[DIM_SOSTANZIALI] != 3).any(axis=1)
    mask_solo_overall = (~mask_eventi) & (judge["score_overall_ethics"] != 3)
    eventi = judge[mask_eventi]
    solo_overall = judge[mask_solo_overall]

    out(f"\n--- PR con un EVENTO di fairness (>=1 dimensione sostanziale !=3) ---")
    out(f"Totale: {len(eventi)} su {n_val}")
    out("Conteggio per agente (NON medie - vedi nota):")
    cnt = eventi["agent"].value_counts()
    for a in AGENTS:
        out(f"  {a:15} {int(cnt.get(a, 0))}")

    # direzione dell'evento: peggioramento (<3) o miglioramento (>3)
    out("\n--- Direzione degli eventi, per dimensione ---")
    righe_dir = []
    for c in DIM_SOSTANZIALI:
        righe_dir.append({
            "dimensione": c.replace("score_", ""),
            "negativi(<3)": int((judge[c] < 3).sum()),
            "positivi(>3)": int((judge[c] > 3).sum()),
        })
    out(fmt_table(pd.DataFrame(righe_dir).set_index("dimensione")))

    if len(eventi) > 0:
        out("\nDettaglio eventi:")
        out(eventi[["pr_id", "agent"] + SCORE_COLS].to_string(index=False))

    out(f"\n--- PR non-neutre SOLO per overall_ethics: {len(solo_overall)} ---")
    if len(solo_overall) > 0:
        out("Sono PR in cui tutte e tre le dimensioni sostanziali sono neutre (3)")
        out("ma il modello ha comunque assegnato un overall diverso da 3. La")
        out("validazione manuale ha confermato che si tratta di un'incoerenza")
        out("della rubrica, non di un segnale: overall_ethics e' generato come")
        out("giudizio libero e non e' vincolato alle dimensioni che sintetizza.")
        out("Queste PR NON sono conteggiate come eventi.")
        out(solo_overall[["pr_id", "agent"] + SCORE_COLS].to_string(index=False))

    per_agente = n_val // len(AGENTS) if len(AGENTS) else 0
    out(f"\nNOTA: NON si riportano le medie dei punteggi per agente. Con "
        f"{n_val - len(eventi)} PR su {n_val} prive di eventi, le medie sarebbero "
        f"tutte ~3.0 e le differenze (dovute a pochi casi isolati su {per_agente} "
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

        # composizione del campione: e' volutamente ARRICCHITO di casi
        # non-neutri, quindi le percentuali di accordo sono una stima
        # CONSERVATIVA e non sono confrontabili con validazioni su campioni
        # prevalentemente neutri.
        jcols = [jc for _, _, jc in dims[:3]]
        if all(c in confronto.columns for c in jcols):
            n_nn_camp = int((confronto[jcols] != 3).any(axis=1).sum())
            out(f"\nPR validate a mano: {len(confronto)}")
            out(f"  di cui con evento secondo il judge: {n_nn_camp} "
                f"({n_nn_camp/len(confronto)*100:.0f}%)")
            out("\nNOTA SULLA COMPOSIZIONE: il campione include TUTTE le PR con")
            out("evento piu' un gruppo di controllo di PR neutre. E' quindi")
            out("volutamente concentrato sui casi difficili: le percentuali di")
            out("accordo sono una stima CONSERVATIVA e non vanno confrontate con")
            out("quelle ottenute su campioni prevalentemente neutri, dove")
            out("l'accordo e' meccanicamente piu' alto.")

        righe_dim = []
        all_diff = []
        forti = []
        for nome, mc, jc in dims:
            if mc in confronto.columns and jc in confronto.columns:
                sub = confronto[[mc, jc]].dropna()
                d = (sub[mc].astype(float) - sub[jc].astype(float)).abs()
                all_diff.extend(d.tolist())
                righe_dim.append({
                    "dimensione": nome,
                    "n": len(sub),
                    "accordo_esatto_%": round((d == 0).mean() * 100, 1),
                    "accordo_entro_1_%": round((d <= 1).mean() * 100, 1),
                    "diff_media": round(d.mean(), 2),
                })
                for idx, val in d.items():
                    if val >= 2:
                        forti.append((confronto.loc[idx, "pr_id"], confronto.loc[idx, "agent"], nome,
                                      confronto.loc[idx, mc], confronto.loc[idx, jc]))

        if righe_dim:
            out("\n--- Accordo per dimensione ---")
            out(fmt_table(pd.DataFrame(righe_dim).set_index("dimensione")))

        if all_diff:
            arr = np.array(all_diff)
            out(f"\nAccordo esatto complessivo:  {(arr == 0).mean()*100:.1f}%")
            out(f"Accordo entro +/-1:          {(arr <= 1).mean()*100:.1f}%")
            out(f"Differenza media assoluta:   {arr.mean():.2f}")

        if forti:
            out("\n--- Disaccordi forti (differenza >= 2) ---")
            for pr_id, ag, dim, mio, jud in forti:
                out(f"  PR {pr_id} ({ag}) {dim}: umano={mio} judge={jud}")

        # Casi confermati dal giudizio umano vs falsi positivi del judge
        mie_cols = [mc for _, mc, _ in dims[:3]]
        jud_cols = [jc for _, _, jc in dims[:3]]
        if all(c in confronto.columns for c in mie_cols + jud_cols):
            conf_um = confronto[(confronto[mie_cols] != 3).any(axis=1)]
            fp_judge = confronto[
                ((confronto[jud_cols] != 3).any(axis=1))
                & ((confronto[mie_cols] == 3).all(axis=1))
                ]
            out(f"\n--- Esito qualitativo della validazione ---")
            out(f"Eventi CONFERMATI dal giudizio umano:      {len(conf_um)}")
            out(f"Eventi del judge NON confermati (falsi positivi): {len(fp_judge)}")
            if len(conf_um) > 0:
                out("\nCasi confermati:")
                cols = ["pr_id", "agent"] + mie_cols
                out(conf_um[cols].to_string(index=False))

        out("\nLETTURA DEI RISULTATI: l'accordo e' pieno sull'accessibilita',")
        out("elevato sulle dimensioni demografica e di linguaggio, basso su")
        out("overall_ethics. Quest'ultimo dato non indica inaffidabilita' del")
        out("judge nel rilevare i fenomeni, ma conferma che overall_ethics non")
        out("e' una sintesi coerente delle altre dimensioni e non va usato come")
        out("indicatore autonomo.")
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
    out(f"\nRighe di log totali: {tot}")
    out(f"  recuperati (after=True): {n_ok} ({n_ok/tot*100:.1f}%)")
    out(f"  falliti (after=False):   {n_fail} ({n_fail/tot*100:.1f}%)")
    out(f"  rimossi (n/a_removed):   {n_removed} ({n_removed/tot*100:.1f}%)")
    out("\nNOTA: il log ha una riga per file PER COMMIT, quindi lo stesso file")
    out("toccato da piu' commit compare piu' volte; i file distinti salvati su")
    out("disco sono meno delle righe con esito positivo.")

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

# Valori calcolati dinamicamente, per non lasciare numeri obsoleti nel testo
_n_pr = len(judge) if judge is not None else "?"
_n_eventi = len(eventi) if judge is not None else "?"
_n_finding = len(gl) if gl is not None else "?"
_n_univoci = n_univoci if (gl is not None and validato) else "?"

out(f"""
RISULTATI PER DIMENSIONE:

- Sustainability (Lizard): e' il segnale piu' solido. OpenAI Codex produce il
  codice piu' complesso per unita' prodotta (CCN media piu' alta, 90esimo
  percentile piu' alto, percentuale maggiore di funzioni oltre le soglie),
  coerentemente con Dou et al. (2026). Il risultato regge al test di robustezza
  che esclude il 5% di funzioni piu' complesse. Il quadro non e' pero'
  monodimensionale: altri agenti guidano su long method e numero di parametri.

- Subject Rights (Gitleaks): {_n_finding} finding grezzi si riducono a
  {_n_univoci} segreti univoci dopo deduplicazione. La validazione manuale ha
  classificato la quasi totalita' come falsi positivi (placeholder, fixtures di
  test, checksum di dipendenze, chiavi pubbliche note di emulatori, valori di
  sviluppo/CI). Un solo caso e' una credenziale reale, introdotta e poi rimossa
  dall'agente nel corso della stessa PR.

- IP Rights (ScanCode): 0 conflitti di licenza e 0 casi di copyright stripping,
  dopo l'esclusione dei file di lock auto-generati e la correzione della tabella
  di compatibilita'.

- Fairness (LLM-judge): {_n_pr} PR valutate senza errori di parsing.
  {_n_eventi} PR presentano un evento di fairness su almeno una delle tre
  dimensioni sostanziali. La validazione manuale su 70 PR (tutte quelle con
  evento piu' un gruppo di controllo) mostra accordo pieno sull'accessibilita',
  elevato su dimensione demografica e linguaggio inclusivo, e basso su
  overall_ethics.

LIMITI DA DICHIARARE:

- Gitleaks e Fairness lavorano sui DIFF, non sui file scaricati: sono immuni al
  problema del recupero file. Lizard e ScanCode usano i file: la perdita
  effettiva sul codice analizzabile e' contenuta e distribuita tra gli agenti.

- Fairness: il diff inviato al judge e' troncato a 100.000 caratteri; una
  minoranza di PR molto grandi resta comunque troncata. Un limite precedente
  piu' basso (10.000) distorceva alcuni giudizi, ed e' stato corretto.

- Fairness: la dimensione 'overall_ethics' non e' una sintesi coerente delle
  altre tre. Il judge le assegna valori non neutri anche quando tutte le
  dimensioni sostanziali sono neutre, e la validazione manuale mostra su questa
  dimensione l'accordo piu' basso. Non va usata come indicatore autonomo.

- Fairness: le segnalazioni piu' severe sul linguaggio inclusivo (punteggio 1)
  non sono state confermate dalla validazione umana. La dimensione va trattata
  con cautela: il judge tende a sovra-segnalare.

- Numeri assoluti piccoli per Gitleaks, ScanCode ed eventi di Fairness: le
  differenze tra agenti sono indicative, non prove statistiche.

- Tabella di compatibilita' licenze semplificata: da sostituire con una matrice
  SPDX completa.

CONTRIBUTO METODOLOGICO:
  Tre delle quattro dimensioni hanno prodotto risultati grezzi fuorvianti,
  corretti solo da validazione manuale o da filtri mirati: i finding di Gitleaks
  (quasi tutti falsi positivi), i conflitti di licenza di ScanCode (generati da
  file di lock e da una tabella di compatibilita' imprecisa) e le metriche di
  complessita' di Lizard (inquinate per il 38% da codice non scritto dagli
  agenti, al punto da invertire il confronto). Il controllo umano sui risultati
  automatici non e' un accessorio della misura: e' parte della misura.
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
    summary["ccn_p90"] = lz.groupby("agent")["ccn"].quantile(0.90).round(2)
    summary["perc_high_ccn"] = (lz.groupby("agent")["high_ccn"].mean() * 100).round(2)
    summary["perc_long_method"] = (lz.groupby("agent")["long_method"].mean() * 100).round(2)
    summary["perc_many_params"] = (lz.groupby("agent")["many_params"].mean() * 100).round(2)
    if gs is not None:
        summary["green_smell_density"] = gs.groupby("agent")["green_smell_density"].mean().round(3)
    if judge is not None:
        summary["eventi_fairness"] = eventi["agent"].value_counts().reindex(AGENTS).fillna(0).astype(int)
    summary = summary.reindex(AGENTS)
    summary.to_csv(REPORT / "riepilogo_per_agente.csv")
    out(f"\n[Salvato] {REPORT / 'riepilogo_per_agente.csv'}")

out(f"[Salvato] {OUT_TXT}")