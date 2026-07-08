"""
06_run_llm_judge.py

Misura la Fairness usando un LLM open-weight come judge sul prompt che hai
gia' preparato (vedi prompts/fairness_judge_prompt.txt).

SETUP DI DEFAULT: OpenRouter con GPT-OSS 120B (variante gratuita).
  - Gratis, nessuna carta di credito richiesta, ma serve un account e una
    API key: https://openrouter.ai -> Settings -> Keys -> Create Key
  - export LLM_JUDGE_API_KEY="<la tua chiave OpenRouter>"
  - Il modello di default e' "openai/gpt-oss-120b:free" - il suffisso
    ":free" e' OBBLIGATORIO, altrimenti la richiesta verrebbe fatturata.
  - Endpoint OpenAI-compatible: https://openrouter.ai/api/v1

  NOTA sulla scelta del modello: si era inizialmente scelto
  "meta-llama/llama-3.3-70b-instruct:free", ma nei test e' risultato
  costantemente sovraccarico ("temporarily rate-limited upstream"),
  praticamente inutilizzabile. GPT-OSS 120B (open-weight, Apache 2.0) si e'
  rivelato piu' disponibile e capace di rispettare lo schema JSON richiesto.
  Per cambiare modello senza toccare il codice:
    export LLM_JUDGE_MODEL="<altro-model-id>"
  (la variabile d'ambiente ha SEMPRE la precedenza su questo default).

LIMITI DEL PIANO GRATUITO DA TENERE PRESENTE:
  - 20 richieste al minuto sui modelli ":free" (non e' un problema reale qui:
    ogni chiamata con un diff lungo richiede comunque diversi secondi).
  - Limite GIORNALIERO: 50 richieste/giorno se non hai mai acquistato
    credito OpenRouter, che sale (permanentemente) a 1000/giorno con un
    acquisto una tantum di 10$ di credito (i modelli ":free" restano
    comunque gratuiti, l'acquisto serve solo a sbloccare il limite piu' alto).
  - Per restare nel piano gratuito puro, lo script e' pensato per essere
    lanciato piu' volte su piu' giorni (es. un agente al giorno se hai
    50 PR/agente): salva ogni risultato SUBITO dopo averlo ottenuto e,
    ad ogni rilancio, SALTA le PR gia' valutate in precedenza, cosi' non
    si spreca quota giornaliera rifacendo chiamate gia' pagate ne' si
    perde il lavoro fatto se l'esecuzione si interrompe a meta'.

"""

import os
import json
import time
import pandas as pd
from pathlib import Path
from openai import OpenAI  # pip install openai --break-system-packages
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
SUBSET_DIR = RESULTS_DIR / "subset"
FAIRNESS_DIR = RESULTS_DIR / "fairness"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
OUTPUT_CSV = FAIRNESS_DIR / "llm_judge_fairness.csv"

# --- Configurazione provider --------------------------------------------
PROVIDER_BASE_URL = os.environ.get("LLM_JUDGE_BASE_URL", "https://openrouter.ai/api/v1")
MODEL_NAME = os.environ.get("LLM_JUDGE_MODEL", "openai/gpt-oss-120b")
API_KEY = os.environ.get("LLM_JUDGE_API_KEY", "")
# SLEEP_BETWEEN_CALLS: con OpenRouter free tier (20 richieste/minuto = 1 ogni
# 3 secondi), un piccolo margine di sicurezza evita di sbattere contro il
# rate limit per via di leggere variazioni di timing.
SLEEP_BETWEEN_CALLS = float(os.environ.get("LLM_JUDGE_SLEEP", "3.5"))
# DIFF_MAX_CHARS: massimo numero di caratteri del diff inviato al modello.
# Oltre questa soglia il diff viene troncato. 100000 (~25k token) e' un buon
# compromesso con gpt-oss-120b (131k token di contesto): tronca solo il ~16%
# delle PR. Configurabile via env per poterlo cambiare senza toccare il codice
DIFF_MAX_CHARS = int(os.environ.get("LLM_JUDGE_DIFF_MAX_CHARS", "100000"))

is_openrouter = "openrouter" in PROVIDER_BASE_URL
if is_openrouter and not API_KEY:
    raise ValueError(
        "Provider OpenRouter richiede una API key gratuita. "
        "Registrati su https://openrouter.ai, vai su Settings -> Keys -> "
        "Create Key, poi: export LLM_JUDGE_API_KEY='...'"
    )

client = OpenAI(base_url=PROVIDER_BASE_URL, api_key=API_KEY or "ollama-non-serve")
log.info(f"Provider: {PROVIDER_BASE_URL} | Modello: {MODEL_NAME}")


def load_already_judged_ids() -> set:
    """
    Ritorna l'insieme dei pr_id gia' valutati CON SUCCESSO (parse_error==False),
    da saltare nelle run successive. Le PR con parse_error==True NON sono
    incluse: verranno cosi' ri-processate automaticamente al prossimo lancio
    (utile per recuperare risposte vuote/troncate dovute a congestione del
    modello gratuito). La rimozione delle vecchie righe fallite dal CSV, per
    evitare duplicati, e' fatta da purge_failed_rows() prima del ciclo.

    Questo e' il cuore del meccanismo "checkpoint": permette di lanciare lo
    script piu' volte su piu' giorni (per restare nel limite giornaliero
    gratuito di OpenRouter) senza ripetere chiamate gia' riuscite.
    """
    if not OUTPUT_CSV.exists():
        return set()
    try:
        existing = pd.read_csv(OUTPUT_CSV)
        if "parse_error" in existing.columns:
            ok = existing[existing["parse_error"] == False]
            return set(ok["pr_id"].tolist())
        return set(existing["pr_id"].tolist())
    except (pd.errors.EmptyDataError, KeyError):
        return set()


def purge_failed_rows():
    """
    Rimuove dal CSV le righe con parse_error==True, cosi' quando quelle PR
    vengono ri-processate (perche' non risultano piu' "gia' fatte con
    successo") non si creano righe duplicate. Va chiamata UNA volta all'avvio,
    prima del ciclo di valutazione. Se dopo la rimozione il CSV resta senza
    righe valide, viene comunque mantenuto l'header.
    """
    if not OUTPUT_CSV.exists():
        return
    try:
        df = pd.read_csv(OUTPUT_CSV)
    except (pd.errors.EmptyDataError, KeyError):
        return
    if "parse_error" not in df.columns:
        return
    n_failed = (df["parse_error"] == True).sum()
    if n_failed == 0:
        return
    kept = df[df["parse_error"] == False]
    kept.to_csv(OUTPUT_CSV, index=False)
    log.info(
        f"Rimosse {n_failed} righe con errore di parsing dalla run precedente: "
        "quelle PR verranno ri-processate in questa run."
    )


def append_result_to_csv(row: dict):
    """
    Scrive UNA riga subito, in append, invece di accumulare tutto in memoria
    e scrivere solo alla fine. Cosi' ogni chiamata riuscita e' salvata su
    disco immediatamente: un'interruzione (rete, rate limit, chiusura
    accidentale) non fa perdere il lavoro gia' fatto.
    """
    row_df = pd.DataFrame([row])
    write_header = not OUTPUT_CSV.exists()
    row_df.to_csv(OUTPUT_CSV, mode="a", header=write_header, index=False)


def load_prompt_template() -> str:
    path = PROMPTS_DIR / "fairness_judge_prompt.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Inserisci il tuo prompt di fairness in {path} "
            "(usa {pr_title}, {pr_body}, {diff} come placeholder testuali - "
            "vengono sostituiti con un replace semplice, non .format(), quindi "
            "eventuali altre graffe nel prompt, es. in uno schema JSON di "
            "esempio, sono al sicuro e non serve raddoppiarle)"
        )
    return path.read_text(encoding="utf-8")


def judge_pr(template: str, pr_title: str, pr_body: str, diff_text: str, max_retries: int = 5) -> dict:
    # NOTA: non si usa template.format(...) perche' il prompt contiene anche
    # un esempio di schema JSON con parentesi graffe letterali (es.
    # {"reasoning": {...}, "scores": {...}}) che .format() interpreterebbe
    # erroneamente come ulteriori placeholder da sostituire, causando un
    # KeyError. Si fa quindi una sostituzione manuale solo dei tre
    # placeholder noti, lasciando intatte tutte le altre graffe nel testo.
    # NOTA sui NaN: title/body/diff possono arrivare come float NaN (pandas usa
    # NaN per i valori mancanti, es. una PR senza descrizione). "x or ''" NON
    # basta a proteggersi, perche' NaN e' "truthy" in Python: NaN or "" -> NaN,
    # e .replace() poi fallisce con "argument must be str, not float". Si
    # converte quindi in modo sicuro a stringa, trattando NaN/None come "".
    def _safe(x):
        if x is None:
            return ""
        # NaN e' l'unico valore diverso da se stesso; cattura i float NaN
        if isinstance(x, float) and x != x:
            return ""
        return str(x)

    prompt = (
        template
        .replace("{pr_title}", _safe(pr_title))
        .replace("{pr_body}", _safe(pr_body))
        .replace("{diff}", _safe(diff_text)[:DIFF_MAX_CHARS])
    )
    # Troncamento diff a DIFF_MAX_CHARS caratteri (vedi costante in cima).
    # STORIA: inizialmente 10000, valore scelto quando si usava un modello
    # locale piccolo (Qwen 3B, poco contesto). Con quel limite, un'analisi
    # a posteriori ha mostrato che il 48% dei diff veniva troncato: il judge
    # valutava quindi meta' delle PR su un changeset PARZIALE (vedi il caso
    # SelectPanel, dove i miglioramenti di accessibilita' erano nella parte
    # tagliata). Passando a gpt-oss-120b via OpenRouter (131k token di
    # contesto) il limite e' stato alzato a 100000 caratteri (~25k token):
    # il troncamento scende al 16%, restando ampiamente dentro il contesto
    # del modello con spazio per prompt e risposta. Le PR con diff oltre
    # 100k char (genuinamente enormi) restano troncate: e' un limite
    # intrinseco, nessun modello le valuterebbe bene "leggendo tutto".

    for attempt in range(max_retries):
        try:
            try:
                # NOTA STORICA (test del 30/06/2026): con response_format=
                # {"type": "json_object"} come PRIMO tentativo, su alcuni
                # modelli ":free" di OpenRouter (osservato con GPT-OSS 120B)
                # si e' verificata una "degenerazione ripetitiva": il modello
                # restava bloccato a generare migliaia di caratteri di
                # spazi/newline (tecnicamente "validi" come contenuto di una
                # stringa JSON) prima e dopo il JSON corretto, rendendo la
                # risposta inutilizzabile pur contenendo il JSON giusto in
                # mezzo al rumore. Sospetto: il vincolo di "grammatica JSON"
                # imposto a basso livello, combinato con temperature=0
                # (decodifica greedy, piu' soggetta a loop di ripetizione),
                # su un'infrastruttura gratuita/quantizzata sotto carico.
                # Si e' quindi invertita la priorita': il tentativo PRIMARIO
                # ora si affida solo alle istruzioni testuali del prompt
                # (gia' molto esplicite sul rispondere solo in JSON), con
                # max_tokens e frequency_penalty come freni anti-loop;
                # response_format resta disponibile come fallback (vedi sotto)
                # per provider/modelli dove invece aiuta piu' che nuocere.
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=2000,  # alzato da 1200: le risposte con reasoning articolato su 3 campi possono superare 1200 token, causando troncamento (parse_error). 2000 lascia margine sufficiente restando comunque un tetto contro loop degeneri.
                    frequency_penalty=0.4,  # scoraggia la ripetizione dello stesso token/frase, contromisura diretta al fenomeno osservato
                )
            except Exception as e_params:
                err_str_inner = str(e_params)
                if "429" in err_str_inner or "rate" in err_str_inner.lower():
                    raise
                log.warning(
                    f"max_tokens/frequency_penalty non supportati da questo "
                    f"provider/modello ({e_params}), ripiego su response_format "
                    "json_object come seconda opzione."
                )
                try:
                    response = client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0,
                        response_format={"type": "json_object"},
                    )
                except Exception as e_json_mode:
                    err_str_inner2 = str(e_json_mode)
                    if "429" in err_str_inner2 or "rate" in err_str_inner2.lower():
                        raise
                    response = client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0,
                    )

            # DIFESA: su OpenRouter, specialmente sui modelli ":free" molto
            # richiesti, un provider sotto carico puo' restituire una
            # risposta HTTP 200 ma con 'choices' vuoto o None (risposta
            # malformata/incompleta), invece di un errore esplicito. Senza
            # questo controllo, response.choices[0] solleva un generico
            # "'NoneType' object is not subscriptable" che non da' nessuna
            # indicazione del problema reale.
            if not response.choices:
                log.warning(
                    f"Tentativo {attempt+1}: risposta priva di 'choices' "
                    "(provider sovraccarico o risposta malformata). Riprovo."
                )
                time.sleep(5 * (attempt + 1))
                continue

            raw_output = response.choices[0].message.content
            return {"raw_output": raw_output, "error": None}

        except Exception as e:
            err_str = str(e)
            if "Connection" in err_str or "connect" in err_str.lower():
                log.error(
                    "Impossibile connettersi al provider. Se usi Ollama, verifica "
                    "che sia in esecuzione ('ollama serve'). Se usi OpenRouter, "
                    "verifica la connessione di rete."
                )

            # DISTINZIONE IMPORTANTE (confermata empiricamente con OpenRouter):
            # - Quota GIORNALIERA esaurita: messaggio specifico contenente
            #   "free-models-per-day" (es. "Rate limit exceeded:
            #   free-models-per-day. Add 10 credits to unlock 1000 free
            #   model requests per day"). Qui ha senso fermarsi subito e
            #   aspettare il giorno dopo.
            # - Congestione TEMPORANEA del modello (molto comune sui modelli
            #   ":free", condivisi tra moltissimi utenti contemporaneamente):
            #   messaggio tipo "is temporarily rate-limited upstream. Please
            #   retry shortly". Qui NON e' la tua quota, e ha senso
            #   ritentare con backoff piu' lungo invece di arrendersi.
            if "free-models-per-day" in err_str.lower() or "free models per day" in err_str.lower():
                log.warning(f"Quota giornaliera del free tier esaurita: {err_str[:200]}")
                return {"raw_output": None, "error": "rate_limited_daily"}

            if "429" in err_str or "rate" in err_str.lower() or "rate-limited" in err_str.lower():
                wait = 15 * (attempt + 1)
                log.warning(
                    f"Tentativo {attempt+1}: congestione temporanea del modello "
                    f"(non quota giornaliera). Riprovo tra {wait}s. Dettaglio: {err_str[:150]}"
                )
                time.sleep(wait)
                continue

            log.warning(f"Tentativo {attempt+1} fallito: {e}")
            time.sleep(2 ** attempt)

    # Esauriti i tentativi senza successo e senza una conferma esplicita di
    # quota giornaliera: non e' detto che sia "quota esaurita", potrebbe
    # essere congestione persistente. Lo segnaliamo comunque come motivo
    # per fermare la run (main() si comporta allo stesso modo: si ferma e
    # invita a riprovare piu' tardi), ma con un messaggio piu' onesto.
    log.warning(
        f"Esauriti {max_retries} tentativi per questa PR senza ottenere una "
        "risposta valida (congestione persistente o problema di rete)."
    )
    return {"raw_output": None, "error": "max_retries_exceeded"}


def extract_balanced_json(text: str) -> str | None:
    """
    Cerca il primo blocco JSON sintatticamente bilanciato in un testo
    potenzialmente "sporco" (con rumore prima/dopo, ripetizioni, o testo
    introduttivo nonostante le istruzioni). Conta le graffe rispettando le
    stringhe tra virgolette (e i caratteri di escape al loro interno), cosi'
    non si confonde se per caso compaiono graffe dentro un valore stringa.

    Trova il primo '{' nel testo e segue l'annidamento fino a tornare a
    profondita' zero: quello e' il blocco JSON completo da provare a
    parsare. Utile in particolare contro fenomeni di "degenerazione
    ripetitiva" del modello (spazi/ripetizioni prima o dopo il JSON vero),
    osservati empiricamente con alcuni modelli ":free" su OpenRouter.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None  # nessun blocco bilanciato trovato (es. risposta troncata)


def parse_judge_output(raw_output: str) -> dict:
    """
    Adattato allo schema specifico del prompt di fairness usato in questo
    progetto (vedi prompts/fairness_judge_prompt.txt), che richiede:
        {
          "reasoning": {"evidenze": "...", "analisi_etica": "...", "valutazione_impatto": "..."},
          "scores": {"demographic_fairness": X, "accessibility_inclusion": X,
                      "inclusive_language": X, "overall_ethics": X},
          "confidence": X
        }
    I campi annidati vengono "appiattiti" in colonne separate (es.
    'score_demographic_fairness', 'reasoning_evidenze', ...) per rendere il
    CSV finale piu' comodo da analizzare con pandas/Excel, invece di lasciare
    colonne con dizionari Python serializzati come stringa.

    Se in futuro cambi lo schema del prompt, aggiorna qui i nomi dei campi.
    """
    empty_result = {
        "score_demographic_fairness": None,
        "score_accessibility_inclusion": None,
        "score_inclusive_language": None,
        "score_overall_ethics": None,
        "confidence": None,
        "reasoning_evidenze": None,
        "reasoning_analisi_etica": None,
        "reasoning_valutazione_impatto": None,
        "parse_error": True,
    }

    if raw_output is None:
        return empty_result

    try:
        # Alcuni modelli (specie quelli "lite") avvolgono il JSON in un
        # blocco markdown ```json ... ``` nonostante le istruzioni - lo
        # rimuoviamo se presente.
        cleaned = raw_output.strip().removeprefix("```json").removesuffix("```").strip()
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError, TypeError):
        # Fallback: il parsing diretto e' fallito (es. output "sporco" con
        # rumore prima/dopo il JSON vero, vedi extract_balanced_json).
        # Si tenta di estrarre il primo blocco JSON bilanciato presente nel
        # testo e si riprova il parsing solo su quello.
        extracted = extract_balanced_json(raw_output) if isinstance(raw_output, str) else None
        if extracted is None:
            result = dict(empty_result)
            result["reasoning_evidenze"] = raw_output  # conserva l'output grezzo per ispezione manuale
            return result
        try:
            parsed = json.loads(extracted)
        except json.JSONDecodeError:
            result = dict(empty_result)
            result["reasoning_evidenze"] = raw_output
            return result

    try:
        scores = parsed.get("scores", {})
        reasoning = parsed.get("reasoning", {})

        return {
            "score_demographic_fairness": scores.get("demographic_fairness"),
            "score_accessibility_inclusion": scores.get("accessibility_inclusion"),
            "score_inclusive_language": scores.get("inclusive_language"),
            "score_overall_ethics": scores.get("overall_ethics"),
            "confidence": parsed.get("confidence"),
            "reasoning_evidenze": reasoning.get("evidenze"),
            "reasoning_analisi_etica": reasoning.get("analisi_etica"),
            "reasoning_valutazione_impatto": reasoning.get("valutazione_impatto"),
            "parse_error": False,
        }
    except (AttributeError, TypeError):
        result = dict(empty_result)
        result["reasoning_evidenze"] = raw_output  # conserva l'output grezzo per ispezione manuale
        return result


def main():
    FAIRNESS_DIR.mkdir(parents=True, exist_ok=True)
    subset_pr = pd.read_parquet(SUBSET_DIR / "subset_pull_requests.parquet")
    subset_commits = pd.read_parquet(SUBSET_DIR / "subset_commit_details.parquet")
    template = load_prompt_template()

    # Rimuove dal CSV le righe fallite (parse_error==True) delle run
    # precedenti, cosi' quelle PR vengono ri-processate senza duplicati.
    purge_failed_rows()

    already_judged = load_already_judged_ids()
    if already_judged:
        log.info(f"Trovate {len(already_judged)} PR gia' valutate con successo in run precedenti, verranno saltate.")

    to_process = subset_pr[~subset_pr["id"].isin(already_judged)]
    if to_process.empty:
        log.info("Tutte le PR del subset sono gia' state valutate. Nulla da fare.")
        return

    log.info(f"PR da valutare in questa run: {len(to_process)} (su {len(subset_pr)} totali nel subset)")
    if is_openrouter:
        log.info(
            "Provider OpenRouter free tier: limite di 50 richieste/giorno (senza "
            "credito acquistato) o 1000/giorno (con 10$ di credito acquistato una "
            "tantum). Se la quota giornaliera si esaurisce a meta', i risultati "
            "fin qui ottenuti restano salvati: rilancia semplicemente lo script "
            "il giorno successivo per proseguire da dove si era interrotto."
        )

    n_processed_this_run = 0
    for _, pr in to_process.iterrows():
        pr_commits = subset_commits[subset_commits["pr_id"] == pr["id"]]
        diff_text = "\n".join(pr_commits["patch"].dropna().astype(str).tolist()) if not pr_commits.empty else ""

        result = judge_pr(template, pr.get("title", ""), pr.get("body", ""), diff_text)

        if result["error"] == "rate_limited_daily":
            log.warning(
                "Quota giornaliera del free tier esaurita (confermato dal messaggio "
                f"del provider). Interrompo qui: {n_processed_this_run} PR valutate "
                f"in questa run, gia' salvate su {OUTPUT_CSV.name}. Rilancia lo "
                "script domani per proseguire."
            )
            break

        if result["error"] == "max_retries_exceeded":
            log.warning(
                "Tentativi esauriti per questa PR senza una risposta valida "
                "(probabile congestione persistente del modello gratuito, non "
                "necessariamente la tua quota giornaliera). Interrompo la run: "
                f"{n_processed_this_run} PR valutate finora restano salvate. "
                "Riprova tra qualche minuto, oppure domani se il problema persiste."
            )
            break

        parsed = parse_judge_output(result["raw_output"])

        row = {
            "pr_id": pr["id"],
            "agent": pr["agent"],
            **parsed,
            "raw_output": result["raw_output"],
            "model": MODEL_NAME,
        }
        append_result_to_csv(row)
        n_processed_this_run += 1

        time.sleep(SLEEP_BETWEEN_CALLS)

    log.info(f"Run completata: {n_processed_this_run} nuove PR valutate e salvate in {OUTPUT_CSV}")

    if not OUTPUT_CSV.exists():
        log.warning(
            "Nessun risultato salvato finora (0 PR valutate con successo in "
            "tutte le run fatte finora). Nessun riepilogo da mostrare."
        )
        return

    final_df = pd.read_csv(OUTPUT_CSV)
    log.info(f"Totale PR valutate finora (incluse run precedenti): {len(final_df)}")
    log.info(f"Parse error rate complessivo: {final_df['parse_error'].mean():.1%}")


if __name__ == "__main__":
    main()
