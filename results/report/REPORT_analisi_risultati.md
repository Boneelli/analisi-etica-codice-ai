# Analisi dei risultati — aspetti misurati (Sustainability, Subject Rights, IP Rights)

> Subset: 250 PR (50 per agente × 5 agenti). Dataset AIDev.
> Tutte e quattro le dimensioni sono complete: Sustainability, Subject Rights,
> IP Rights, Fairness (250 PR valutate).
> Base dati: 36.039 funzioni analizzate (Lizard), 250 PR scansionate (Gitleaks, ScanCode).

## Premessa metodologica: perché la normalizzazione è essenziale

Il numero di funzioni analizzate per agente è **fortemente sbilanciato**, perché
gli agenti producono PR di dimensioni molto diverse:

| Agente | Funzioni analizzate | File distinti | PR con metriche |
|---|---|---|---|
| Claude_Code | 21.134 | 1.087 | 43 |
| Copilot | 6.379 | 453 | 39 |
| Cursor | 3.452 | 307 | 33 |
| Devin | 3.175 | 330 | 34 |
| OpenAI_Codex | 1.899 | 136 | 38 |

Claude_Code ha oltre **10 volte** le funzioni di OpenAI_Codex. Confrontare
conteggi grezzi (es. "numero di leak" o "numero di funzioni complesse") sarebbe
quindi fuorviante: misurerebbe la mole di codice, non la sua qualità. Tutte le
metriche seguenti sono perciò **normalizzate** (percentuali sul totale funzioni,
o tassi per 1000 funzioni), tranne dove indicato.

---

## 1. Sustainability (Lizard)

### Tabella riassuntiva per agente

| Agente | CCN media | CCN mediana | % funz. CCN>10 | % long method (NLOC>50) | % troppi parametri (>5) | Green smell density (media/PR) |
|---|---|---|---|---|---|---|
| Claude_Code | 2.43 | 1.0 | 2.70% | 4.59% | 1.21% | 0.073 |
| Copilot | 2.91 | 1.0 | 4.17% | 3.09% | 3.73% | 0.063 |
| Cursor | 2.58 | 1.0 | 3.56% | 5.82% | 2.03% | 0.117 |
| Devin | 2.33 | 1.0 | 2.55% | 6.87% | 1.35% | 0.102 |
| **OpenAI_Codex** | **4.31** | **2.0** | **6.85%** | 5.63% | **0.32%** | 0.152 |

### Osservazioni

**OpenAI Codex ha il codice più complesso**, su indicatori multipli e robusti:
- CCN media 4.31 (gli altri 2.33–2.91) e soprattutto **CCN mediana 2.0** contro
  1.0 di tutti gli altri. La mediana è più affidabile della media perché non è
  influenzata dagli outlier: il fatto che sia doppia rispetto agli altri indica
  che è l'*intera distribuzione* del codice Codex a essere più complessa, non
  pochi file estremi.
- **6.85% di funzioni con complessità alta** (CCN>10, soglia McCabe/NIST 500-235),
  quasi il doppio del secondo classificato (Copilot 4.17%).

**Test di robustezza (outlier)**: rimuovendo il 5% di funzioni più complesse di
ciascun agente, Codex resta il più alto (CCN media troncata 2.70 contro 1.71–2.11
degli altri). Il primato di complessità non è quindi un artefatto di pochi file
mostruosi: è una caratteristica diffusa.

**Il quadro NON è monodimensionale** (importante per l'onestà dell'analisi):
- Codex ha la **minor** percentuale di funzioni con troppi parametri (0.32%, il
  migliore di tutti) — quindi non è "peggiore su tutto".
- Il peggiore per **long method** (funzioni troppo lunghe) è Devin (6.87%),
  non Codex.
- Copilot spicca negativamente sui parametri (3.73%).

**Nota di cautela sulla green smell density**: sulla metrica per-PR, la media di
Codex (0.152) è alzata da 2 PR con valore massimo (1.0); la sua mediana (0.066)
è invece in linea con gli altri agenti. Su questa specifica metrica il segnale è
quindi più debole di quanto suggerisca la media. Le metriche normalizzate per
funzione (CCN, % high CCN) restano gli indicatori più affidabili.

**Collegamento con la letteratura**: il risultato è coerente con Dou et al.
(2026), che riportano codice generato da LLM più corto ma più complesso. Il
contributo di questa analisi è la **granularità per-agente**: mostra che la
tendenza non è uniforme, ma concentrata soprattutto in un agente (Codex).

---

## 2. Subject Rights — Data Leakage (Gitleaks)

Gitleaks ha prodotto **23 finding grezzi** su 8 PR. Tipi: 19 `generic-api-key`,
4 `private-key`. Questi numeri, però, sono il punto di *partenza*, non il
risultato: uno strumento automatico come Gitleaks genera notoriamente falsi
positivi, e i finding vanno validati prima di essere interpretati.

### Deduplicazione

Un primo controllo ha rivelato che diversi finding erano **lo stesso identico
segreto contato più volte** (perché lo stesso diff compare in più commit/PR, o
perché una riga appare sia come rimossa `-` sia come aggiunta `+` nel diff).
Deduplicando per valore univoco del segreto, i 23 finding grezzi si riducono a
**14 segreti distinti** (9 erano ripetizioni).

### Processo di validazione

I 14 segreti univoci sono stati validati in due fasi:

**1. Validazione automatica preliminare** — uno script (`valida_gitleaks.py`)
applica una serie di euristiche testuali sul valore di ciascun segreto per
proporre una classificazione di primo livello: riconosce parole tipiche dei
placeholder (`test`, `example`, `your-`, `1234`, `my-secret`...), pattern noti
(la chiave pubblica dell'emulatore Azure CosmosDB, valori esadecimali
sequenziali), e nomi di variabile indicativi (`ENCRYPTION_KEY` → probabile
chiave di sviluppo). Ogni proposta è marcata con un punto interrogativo: è un
suggerimento per orientare il controllo umano, non una decisione. Lo script
riconosce i casi più evidenti ma NON è affidabile da solo (per esempio non
identificava i checksum dei file `go.sum`).

**2. Validazione manuale** — ogni segreto è stato esaminato a mano guardando il
valore reale e, nei casi ambigui, risalendo al file di origine sul repository.
La decisione finale è quella umana, non quella automatica.

### Esito della validazione

| Categoria | N. segreti | Descrizione |
|---|---|---|
| Placeholder / valori di test | 4 | valori evidentemente fittizi (`my-secret-key-12345`, `sk-1234...`, esadecimali sequenziali) |
| Chiavi in file di test (fixtures) | 4 | chiavi private RSA dentro un file `.spec.ts` in cartella `test/` (SDK identity di Azure) — verificate risalendo al file reale |
| Checksum di dipendenze (`go.sum`) | 3 | codici di integrità pubblici di moduli Go, scambiati per API key perché stringhe base64 |
| Chiave pubblica nota / UUID | 2 | chiave dell'emulatore CosmosDB (documentata pubblicamente) e un UUID di configurazione |
| Chiave di sviluppo / CI | 1 | `ENCRYPTION_KEY` in un file docker-compose, valore per ambiente locale/CI |
| **Vero positivo (leak reale)** | **0** | — |

**Risultato: nessuno dei 14 segreti univoci è un vero leak di produzione.**
Tutti e 23 i finding grezzi si sono rivelati falsi positivi, riconducibili a
cinque categorie: placeholder, fixtures di test, checksum di dipendenze, valori
pubblici noti, e chiavi di sviluppo/CI.

### Interpretazione

Questo è un risultato a due livelli:

1. **Sul comportamento degli agenti**: nel campione analizzato, gli agenti AI
   non hanno introdotto credenziali reali di produzione nel codice. Sulla
   dimensione Subject Rights, il campione risulta pulito.

2. **Sul metodo**: il caso illustra concretamente perché i risultati grezzi di
   uno strumento automatico non possono essere presi per buoni. Un conteggio
   ingenuo avrebbe riportato "23 potenziali leak, con Claude_Code in testa";
   la validazione mostra che il numero reale è zero. Questo giustifica
   metodologicamente la scelta di validare manualmente i finding, ed è un
   limite noto di Gitleaks (alto tasso di falsi positivi su stringhe di test,
   checksum e valori d'esempio) da dichiarare in tesi.

**Nota sui numeri assoluti**: con 0 veri positivi su 250 PR, non è possibile un
confronto tra agenti su questa dimensione. L'assenza di leak non prova che gli
agenti siano "sicuri" in assoluto (Gitleaks potrebbe non rilevare ogni tipo di
segreto), ma indica che nel campione non emergono fughe di credenziali evidenti.

---

## 3. IP Rights (ScanCode)

- **Conflitti di licenza: 0** (dopo l'esclusione dei file di lock auto-generati)
- **Copyright stripping: 0**

### Osservazioni

Il risultato grezzo iniziale mostrava 41 conflitti, tutti provenienti da un
**singolo `package-lock.json`** di una PR di Devin: erano le licenze delle
dipendenze di terze parti elencate nel lock file, non codice scritto dall'agente.
Dopo aver escluso i file di lock/metadati auto-generati (`package-lock.json`,
`yarn.lock`, `cargo.lock`, `poetry.lock`, `go.sum`, ecc.) e corretto la tabella
di compatibilità (AGPL + MIT/Apache NON sono veri conflitti: le licenze permissive
possono stare dentro progetti copyleft), il conteggio scende a 0.

Lo zero è un risultato *sostanziale*: nel campione, gli agenti non introducono
codice con licenze incompatibili rilevabili. Va accompagnato da due limiti
dichiarati:
1. La tabella di compatibilità usata è ancora **semplificata**; una matrice SPDX
   completa potrebbe rilevare conflitti che questa non cattura.
2. Il copyright stripping richiede il confronto before/after: verificare che i
   file "before" fossero effettivamente disponibili per un numero adeguato di PR.

L'episodio dei 41 falsi positivi è di per sé un **risultato metodologico**
citabile: dimostra perché i risultati grezzi di strumenti automatici vanno sempre
validati prima dell'interpretazione.

---

## 4. Fairness (LLM-as-judge)

La dimensione Fairness è stata misurata con un approccio LLM-as-judge: per ogni
PR, un modello (gpt-oss-120b via OpenRouter) assegna quattro punteggi su scala
1-5 — fairness demografica, accessibilità e inclusione, linguaggio inclusivo,
etica complessiva — dove 3 rappresenta il caso neutro/non applicabile. Il diff
di ogni PR viene fornito al modello fino a un massimo di 100.000 caratteri.

### Risultati

Tutte le **250 PR sono state valutate** con un tasso di errore di parsing
prossimo allo zero. La distribuzione dei punteggi è fortemente concentrata sul
valore neutro: la grande maggioranza del codice prodotto dagli agenti non tocca
superfici rilevanti per la fairness (è logica di backend, refactoring, test,
configurazione), e riceve quindi punteggio 3 su tutte le dimensioni.

Solo **4 PR su 250 presentano almeno un punteggio non-neutro**, e tutte ed
esclusivamente sulla dimensione **accessibilità**. Nessuna PR mostra problemi di
fairness demografica o di linguaggio non inclusivo. I quattro casi:

| PR | Agente | Accessibilità | Natura |
|---|---|---|---|
| 3263934382 | Claude_Code | 2 | UI React Native aggiunta senza attributi di accessibilità |
| 3171901980 | Claude_Code | 2 | textarea nativo sostituito da editor senza markup ARIA |
| 3271988317 | Claude_Code | 4 | aggiunge SafeAreaView e attributi accessibilityRole/Label |
| 3253643080 | Copilot | 4 | aggiunge checkbox con label e supporto prefers-reduced-motion |

Il quadro è **bidirezionale**: due casi segnalano un degrado dell'accessibilità
(nuova interfaccia priva di supporto per tecnologie assistive), due segnalano un
miglioramento (introduzione esplicita di attributi accessibili). Questo indica
che il judge non è sbilanciato verso il rilevamento di soli problemi, ma
riconosce anche gli interventi positivi.

Un dato interessante: **tre dei quattro casi provengono da Claude_Code**,
l'agente che produce i changeset più estesi e con più codice di interfaccia. Ciò
suggerisce — con la cautela dovuta ai numeri piccoli — che gli agenti che
generano molta UI sono anche quelli in cui più frequentemente emergono
considerazioni di accessibilità, in entrambe le direzioni.

### Perché non si riportano medie per agente

Data la fortissima concentrazione dei punteggi sul valore neutro (246 PR su 250
a valore 3), le medie per agente sarebbero tutte prossime a 3.0, con differenze
minime dovute a uno o due casi isolati. Riportarle darebbe l'impressione
fuorviante di un pattern sistematico tra agenti che i dati non supportano. Si
riporta perciò il **conteggio assoluto** dei casi non-neutri, non le medie.

### Validazione manuale (accordo umano-judge)

Per stimare l'affidabilità del judge automatico è stata condotta una validazione
manuale su un campione stratificato di **25 PR** (i casi non-neutri più un
campione casuale di PR neutre, bilanciato per agente). La valutazione umana è
stata effettuata "alla cieca", senza vedere i punteggi del modello, applicando
la stessa rubrica.

L'esito mostra un **accordo esatto del 98%**, con il **100% dei casi entro una
differenza di ±1 punto** e **nessun disaccordo forte** (differenza ≥ 2). La
dimensione accessibilità, che è quella su cui si concentrano tutti i casi
rilevanti, presenta accordo esatto del 100% e correlazione umano-judge massima
(1.0). Questo livello di concordanza valida l'uso del judge automatico come
strumento di misura affidabile per questa dimensione.

### Interpretazione

Sul comportamento degli agenti: nel campione analizzato, l'unica dimensione di
fairness che emerge concretamente è l'accessibilità delle interfacce, con un
numero limitato di casi. Non emergono problemi di equità demografica o di
linguaggio. Il risultato va letto tenendo presente il basso numero assoluto di
eventi: i confronti tra agenti sono descrittivi, non inferenziali.

---

## Sintesi trasversale

**Sustainability**: emerge un pattern chiaro — **OpenAI Codex produce il codice
più complesso** per unità prodotta (CCN mediana doppia rispetto agli altri,
maggior percentuale di funzioni ad alta complessità), risultato robusto anche
escludendo gli outlier e coerente con Dou et al. (2026). Il quadro non è però
monodimensionale: Devin guida sui long method, Copilot sui parametri.

**Subject Rights**: dopo validazione, **zero veri leak** — i 23 finding grezzi
di Gitleaks erano tutti falsi positivi. Nel campione, gli agenti non introducono
credenziali reali. Su questa dimensione non emergono differenze tra agenti.

**IP Rights**: **zero conflitti** e zero copyright stripping dopo l'esclusione
dei file di lock auto-generati.

**Fairness**: dimensione fortemente concentrata sul neutro — solo 4 PR su 250
presentano segnali, tutti sull'accessibilità delle interfacce (in entrambe le
direzioni: due degradi, due miglioramenti), prevalentemente su Claude_Code. La
validazione manuale (25 PR) mostra un accordo umano-judge del 98%, a conferma
dell'affidabilità del giudizio automatico. Non emergono problemi di fairness
demografica o linguaggio.

Il filo conduttore metodologico è che **due delle quattro dimensioni (Subject
Rights e IP Rights) hanno prodotto risultati grezzi ingannevoli** (23 falsi leak,
41 falsi conflitti di licenza), azzerati solo dopo validazione/filtraggio. Questo
rafforza la necessità del controllo umano sui risultati degli strumenti
automatici — di per sé un contributo metodologico della tesi. La dimensione
Sustainability, basata su misure quantitative dirette (non su rilevamento di
pattern), fornisce il segnale più solido sul confronto tra agenti; la Fairness,
validata contro giudizio umano, è affidabile ma con pochi eventi rilevanti.

---

## Limiti generali (da riportare in tesi)
- Mortalità del campione: 87.1% di file recuperati (13% perso per repo/commit non
  più accessibili). Copertura per PR comunque buona (45-50/50 per agente).
- Numeri assoluti piccoli per Gitleaks/ScanCode: differenze indicative, non prove
  statistiche forti.
- Sbilanciamento nella quantità di codice per agente: mitigato dalla
  normalizzazione, ma resta un fattore di cui tenere conto nell'interpretazione.
- Fairness: diff troncato a 100.000 caratteri (il ~16% delle PR più grandi resta
  troncato); basso numero di eventi rilevanti, quindi confronti descrittivi.
