# Setup esperimento tesi — Misurazione qualità del codice prodotto da agenti AI

> Gitleaks, Lizard, ScanCode girano in locale.
> Per il recupero dei file si usano solo GitHub raw URL e API.
> Per l'LLM judge si usa OpenRouter con GPT-OSS 120B (anche variante gratuita `:free`)

## Dimensioni misurate

| Dimensione | Metrica | Tool                                 |
|---|---|--------------------------------------|
| Subject Rights | Data Leakage (chiavi API, password, PII) | Gitleaks                             |
| Sustainability | Green Smell Density + Complessità Ciclomatica (proxy energia) | Lizard                               |
| IP Rights | Conflitti di licenza + Copyright Stripping | ScanCode Toolkit                     |
| Fairness | Valutazione LLM-as-judge | GPT-OSS 120B (OpenRouter) |

## Dataset

[AIDev](https://huggingface.co/datasets/hao-li/AIDev) — usare la sotto-versione
**AIDev-pop** (repository con >100 stelle), perché è anche la sola che fornisce
`pr_commits` / `pr_commit_details` con le patch. La tabella generale
`all_pull_request` ha solo metadati, niente codice.

⚠️ Nota dal changelog del dataset: `pr_commit_details` non include le patch
troppo grandi (limite dell'API GitHub). Per quelle PR vanno scaricate a parte
le versioni complete dei file (vedi `02_fetch_files.py`).

## Niente clone di interi repository

Il dataset fornisce solo diff testuali, insufficienti per Lizard (serve il
corpo completo delle funzioni) e ScanCode (license/copyright detection
richiede contesto oltre le righe toccate dal diff). La soluzione adottata
**non clona repository intere**: scarica solo i singoli file necessari
tramite `raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}`, sia nella
versione post-merge ("after") che, se serve il copyright stripping, nella
versione pre-PR ("before", al commit padre). Si scarica anche, una sola
volta per repo, il file LICENSE/COPYING della root — utile come confronto
secondario rispetto alla colonna `repository.license` dei metadati AIDev
(es. per individuare casi di "permissive washing", dove il file dichiara
una licenza diversa da quella nei metadati del progetto).

Questo riduce drasticamente storage e tempo rispetto al clone, al costo di
perdere il contesto repo-level più ampio (struttura cartelle, file non
toccati dalla PR) — accettabile per le metriche di questo esperimento,
perché si vuole comunque isolare il contributo specifico dell'agente.

## Ordine di esecuzione per la riproducibilità

```bash
pip install -r requirements.txt --break-system-packages

# 1. Costruzione subset da AIDev
python scripts/01_build_subset.py --agents Claude_Code OpenAI_Codex --n-per-agent 50

# 2. Recupero dei singoli file (after + before) via raw.githubusercontent.com
#    Impostare un token GitHub per evitare il rate limit sull'API (60 req/h
#    senza token, 5000 req/h con token) usata per ottenere lo SHA del commit padre.
export GITHUB_TOKEN="..."
python scripts/02_fetch_files.py

# 3. Data leakage
python scripts/03_run_gitleaks.py patch   # oppure "repo" per la baseline

# 4. Sostenibilità
python scripts/04_run_lizard.py

# 5. IP rights
python scripts/05_run_scancode.py

# 6. Fairness — OpenRouter con GPT-OSS 120B, variante gratuita
#
#    1. Registrati su https://openrouter.ai (gratis, nessuna carta richiesta)
#    2. Settings -> Keys -> Create Key, copia la chiave
#    3. export LLM_JUDGE_API_KEY="<la tua chiave>"
#    4. Lancia lo script:
python scripts/06_run_llm_judge.py
```

⚠️ **Fare attenzione ai limiti del piano gratuito — dettagli pratici**:


## Schema del dataset

Le tabelle effettivamente necessarie e le colonne usate dagli script:

| Tabella | Colonne usate | Note                                                                                            |
|---|---|-------------------------------------------------------------------------------------------------|
| `pull_request` | `id`, `agent`, `repo_id`, `repo_url`, `merged_at`, `title`, `body` | `agent` identifica il coding agent                                                              |
| `repository` | `id`, `language`, `license` | `license` (es. "MIT", "Apache-2.0"); diventa `repo_license` dopo il join in `01_build_subset.py` |
| `pr_commits` | `pr_id`, `sha` | Tabella ponte tra `pull_request` e `pr_commit_details`                                          |
| `pr_commit_details` | `sha`, `pr_id`, `filename`, `status`, `patch` | `status` ∈ {added, modified, removed, renamed}                     |



## Limiti metodologici

- **Green Smell Density** non è una metrica standard/nativa di Lizard: è
  costruita applicando soglie (configurabili in
  `configs/green_smells_thresholds.json`) alle metriche grezze di Lizard
  (CCN, NLOC, parametri, nesting). Le soglie sono un parametro di
  ricerca — giustificate con riferimenti alla letteratura.
- **Mortalità del campione**: una parte dei repository GitHub referenziati
  da AIDev può risultare non più accessibile (repo privati, rinominati,
  cancellati) al momento dell'esperimento, perché il dataset è stato
  raccolto in passato. Il tasso di "checkout falliti" è documentato
  (`results/checkout_log.csv`) come parte della validità dello studio.
- **LLM-as-judge**: si usa GPT-OSS 120B via OpenRouter (anche variante
  gratuita `:free`), uno dei modelli open-weight più usati in letteratura
  come judge, scelto anche per la sua affidabilità nel rispettare schemi di
  output JSON complessi (a differenza di modelli più piccoli, con cui sono
  stati osservati empiricamente tassi di errore di parsing molto alti su
  questo stesso prompt). Resta comunque valido il vantaggio di
  riproducibilità tipico dei modelli open-weight: i pesi sono pubblici e
  chiunque può riprodurre l'esperimento scaricando lo stesso checkpoint in
  locale, anche se per comodità qui si è usato un servizio gratuito di terze
  parti (OpenRouter) invece dell'inferenza locale. Va dichiarato che i
  modelli ":free" su OpenRouter sono serviti da provider sottostanti che
  possono cambiare nel tempo: per la riproducibilità, oltre al nome del
  modello, vale la pena annotare la data delle chiamate API. Si è comunque
  validato un sottocampione con un giudizio  umano e calcolato l'accordo umano-modello, 
  riportato come misura di affidabilità della metrica.
