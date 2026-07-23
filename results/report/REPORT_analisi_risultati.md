# Analisi dei risultati — le quattro dimensioni etiche

> Campione finale: **1000 Pull Request** (200 per ciascuno dei 5 agenti),
> estratte da AIDev-pop con campionamento stratificato e seed fisso.

---

## Premessa metodologica

Due accorgimenti condizionano la lettura di tutti i risultati che seguono e
vanno esplicitati prima delle tabelle.

### Normalizzazione

Gli agenti producono quantità di codice molto diverse tra loro: a parità di 200
PR ciascuno, il numero di funzioni analizzate va dalle 49.801 di Claude Code
alle 8.925 di OpenAI Codex, con un rapporto di circa 5 a 1. Qualsiasi conteggio
assoluto (numero di funzioni complesse, numero di finding di sicurezza)
premierebbe automaticamente chi scrive meno codice. Tutte le metriche sono
perciò normalizzate: percentuali sul totale delle funzioni, o tassi per unità
di codice prodotto.

### Esclusione del codice non scritto dagli agenti

Una Pull Request può contenere file che l'agente non ha materialmente scritto:
dipendenze copiate nel repository (*vendoring*), codice generato
automaticamente da strumenti (client protobuf, ORM), artefatti di build
(bundle JavaScript minificati). Misurarne la complessità e attribuirla
all'agente è scorretto: la metrica descriverebbe la libreria di terzi o il
generatore, non il lavoro dell'agente.

L'effetto, sul campione, è tutt'altro che marginale: **il 38,4% delle funzioni
inizialmente analizzate (87.052 su 226.965) ricadeva in questa categoria**. E
soprattutto la distribuzione è fortemente **asimmetrica**: riguardava il 59,9%
delle funzioni attribuite a Claude Code e il 24,4% di quelle di Copilot, contro
percentuali prossime allo zero per gli altri tre agenti. Un singolo file — una
copia vendorizzata di SQLite tradotta da C a Go — contribuiva da solo con oltre
4.000 funzioni, replicate in tredici varianti per architettura all'interno
della stessa PR.

Senza questo filtro, il confronto tra agenti risultava **invertito**: Claude
Code appariva l'agente con il codice più complesso (CCN media 4,58) mentre, una
volta escluso il codice non suo, risulta tra i più contenuti (2,51). È il primo
dei casi, ricorrenti in questo lavoro, in cui il risultato grezzo di uno
strumento automatico è fuorviante.

---

## 1. Sustainability (Lizard)

Metriche calcolate su **139.913 funzioni** appartenenti a **681 PR** (le
rimanenti non contengono codice sorgente analizzabile: toccano solo
documentazione, configurazione o file non recuperabili).

### Complessità ciclomatica per funzione

| Agente | n. funzioni | media | mediana | 90° perc. | max |
|---|---|---|---|---|---|
| Claude Code | 49.801 | 2,51 | 1,0 | 5,0 | 408 |
| Copilot | 39.478 | 3,01 | 1,0 | 6,0 | 906 |
| Cursor | 27.477 | 3,42 | 1,0 | 7,0 | 1356 |
| Devin | 14.232 | 2,56 | 1,0 | 5,0 | 286 |
| **OpenAI Codex** | 8.925 | **4,01** | 1,0 | **8,0** | 413 |

La mediana è pari a 1,0 per tutti gli agenti: la maggioranza delle funzioni, in
qualsiasi codebase, è banale. Il confronto va quindi letto sulla media, sul 90°
percentile e sulla percentuale di funzioni oltre soglia, non sulla mediana.

### Test di robustezza

Poiché la media è sensibile ai valori estremi, è stata ricalcolata escludendo
il 5% di funzioni più complesse:

| Agente | media completa | media troncata al 95° |
|---|---|---|
| Claude Code | 2,51 | 1,79 |
| Copilot | 3,01 | 1,96 |
| Cursor | 3,42 | 2,23 |
| Devin | 2,56 | 1,85 |
| **OpenAI Codex** | **4,01** | **2,53** |

L'ordinamento resta invariato: il primato di Codex non dipende da pochi
outlier.

### Green smell, normalizzati sul numero di funzioni

| Agente | CCN > 10 | metodo > 50 righe | > 5 parametri |
|---|---|---|---|
| Claude Code | 3,09% | 4,22% | 1,64% |
| Copilot | 4,00% | 4,81% | 2,45% |
| Cursor | 5,14% | 5,19% | 2,11% |
| Devin | 3,04% | **6,92%** | 2,02% |
| OpenAI Codex | **7,32%** | 6,15% | 0,72% |

### Osservazioni

**OpenAI Codex produce il codice più complesso per unità prodotta.** Ha la
media più alta (4,01), il 90° percentile più alto (8,0) e più del doppio delle
funzioni oltre la soglia critica di complessità rispetto a Claude Code (7,32%
contro 3,09%).

**Il quadro non è però monodimensionale.** Devin guida sulla percentuale di
metodi lunghi (6,92%), Copilot sui parametri in eccesso (2,45%), e proprio
Codex ha la percentuale più bassa di funzioni con troppi parametri (0,72%). Gli
agenti hanno cioè profili di debolezza diversi, non una qualità
complessivamente ordinabile.

**La densità di green smell per PR** conferma il quadro: Codex ha la densità
media più alta (0,156, mediana 0,100), gli altri agenti si collocano tra 0,084
e 0,110. Trattandosi di una metrica per-PR, è più sensibile a singole PR
anomale rispetto alle metriche per-funzione, che restano la base di confronto
più solida.

---

## 2. Subject Rights — Data Leakage (Gitleaks)

Gitleaks è stato applicato ai soli **diff** delle PR, cioè alle righe
effettivamente aggiunte o modificate dagli agenti, per circoscrivere l'analisi
al codice di cui l'agente è responsabile.

### Risultati grezzi

**98 finding su 28 PR distinte**, così ripartiti per tipo di regola:

| Regola | n. |
|---|---|
| generic-api-key | 60 |
| curl-auth-header | 20 |
| stripe-access-token | 6 |
| private-key | 5 |
| slack-webhook-url | 5 |
| algolia-api-key | 1 |
| slack-bot-token | 1 |

### Deduplicazione

Molti finding sono occorrenze ripetute dello stesso valore, sia perché il
medesimo segreto compare in più file, sia perché una PR con più commit ripete
la stessa riga. Raggruppando per valore univoco, i **98 finding grezzi si
riducono a 47 segreti distinti** (51 erano duplicati).

### Esito della validazione manuale

Ogni segreto univoco è stato esaminato a mano, risalendo al file originale e al
contesto d'uso, e classificato in una di queste categorie:

- **FP_test** — valore in file di test, fixture o documentazione
- **FP_notsecret** — placeholder, valore pubblico noto, dato non sensibile
- **FP_dev_ci** — chiave di sviluppo o CI, non di produzione
- **VP** — credenziale reale presente nel codice consegnato
- **VP_Rimediato** — credenziale reale introdotta e poi rimossa nella stessa PR

**Leak persistenti nel codice consegnato: 0.**
**Leak rimediati nel corso della stessa PR: 1.**
**Falsi positivi: 46 su 47 segreti univoci.**

I falsi positivi comprendono placeholder testuali (`your_api_key_here`,
`sk-1234567890abcdef`), chiavi RSA contenute in test di regressione TLS,
checksum di dipendenze Go (`go.sum`), chiavi pubblicamente documentate degli
emulatori Azure CosmosDB e Azurite, chiavi dell'ambiente *test* di Stripe
(`sk_test_`), token di paginazione e identificativi UUID.

### Il caso rimediato

L'unico segreto reale rilevato è un **URL di trigger Slack** in una PR di Devin
(3220699146), inserito in `pcweb/constants.py`, cioè in codice applicativo e
non in test o documentazione. La sequenza interna alla PR è però istruttiva:
l'agente introduce l'URL come costante, poi lo sposta su variabile d'ambiente
mantenendolo come valore di ripiego, infine rimuove del tutto il ripiego. Lo
stato finale della PR è pulito.

Il caso è stato classificato a parte perché non è né un falso positivo né un
leak persistente: il segreto **resta comunque nella storia dei commit**, e la
prassi di sicurezza richiederebbe la rotazione della credenziale, non la sola
rimozione. È anche l'unico esempio, nel campione, di auto-correzione di un
errore da parte di un agente all'interno della stessa PR — un comportamento che
nessuna metrica aggregata avrebbe mostrato.

### Interpretazione

Il conteggio grezzo (98 finding, con Claude Code a 45 e Cursor a 0) avrebbe
suggerito differenze marcate tra agenti. La deduplicazione e la validazione
mostrano che si tratta quasi interamente di rumore. Il tasso di falsi positivi
di Gitleaks su questo materiale è del **98%** (46 su 47), e la differenza tra
agenti nel conteggio grezzo riflette soprattutto quanta documentazione con
esempi di comandi `curl` ciascuno produce.

---

## 3. IP Rights (ScanCode)

**Conflitti di licenza: 0. Casi di copyright stripping: 0.**

Su 1000 PR ne sono state scansionate 943; 56 non avevano file recuperabili e
una è fallita per un formato non gestito (file di ontologia `.obo`).

### Osservazioni

Lo zero è il risultato ottenuto **dopo due correzioni**, entrambe necessarie:

1. **Esclusione dei file di lock auto-generati** (`package-lock.json`,
   `yarn.lock`, `go.sum`, ecc.). Questi file elencano le licenze di tutte le
   dipendenze transitive del progetto: non sono codice scritto dall'agente, e
   la loro inclusione generava decine di falsi conflitti, tutti provenienti da
   un singolo file.
2. **Correzione della tabella di compatibilità.** Le coppie del tipo
   AGPL + MIT erano classificate come incompatibili, ma non lo sono: una
   licenza permissiva può legittimamente essere inclusa in un progetto
   copyleft. La compatibilità tra licenze è **direzionale**, e trattarla come
   simmetrica produceva errori sistematici.

Lo zero va accompagnato da due limiti dichiarati. La tabella di compatibilità
resta semplificata rispetto a una matrice SPDX completa, che potrebbe rilevare
casi qui non catturati. E la rilevazione del copyright stripping richiede il
confronto *before/after*, disponibile per la maggior parte ma non per la
totalità delle PR.

---

## 4. Fairness (LLM-as-judge)

**1000 PR valutate, nessun errore di parsing.** Il modello assegna quattro
punteggi su scala 1–5, dove 3 rappresenta il caso neutro o non applicabile.

### Definizione di evento

Si considera **evento di fairness** una PR con almeno un punteggio diverso da 3
su una delle tre dimensioni sostanziali: fairness demografica, accessibilità e
inclusione, linguaggio inclusivo. La quarta dimensione, `overall_ethics`, è una
sintesi prodotta liberamente dal modello e **non entra nella definizione**, per
le ragioni discusse più avanti.

**Eventi rilevati: 51 su 1000 PR.** A queste si aggiungono 3 PR non-neutre
*soltanto* per `overall_ethics`, escluse dal conteggio.

| Agente | eventi |
|---|---|
| Devin | 14 |
| Claude Code | 13 |
| Cursor | 12 |
| Copilot | 6 |
| OpenAI Codex | 6 |

### Direzione degli eventi

| Dimensione | peggioramenti (< 3) | miglioramenti (> 3) |
|---|---|---|
| accessibilità | 10 | 32 |
| fairness demografica | 6 | 0 |
| linguaggio inclusivo | 4 | 0 |

Il dato più rilevante è che **la maggioranza degli eventi sono miglioramenti**,
concentrati sull'accessibilità: PR che introducono attributi ARIA, etichette
per screen reader, supporto a `prefers-reduced-motion`. Il judge non è dunque
sbilanciato verso il solo rilevamento di problemi.

### Il caso sostanziale

La segnalazione più significativa riguarda la **PR 3185859728 (Claude Code)**,
in cui una funzione di *fraud detection* utilizza un elenco di paesi come
criterio di rischio. È l'unico caso, nel campione, in cui la validazione umana
ha confermato una logica potenzialmente discriminatoria su base demografica —
non un problema di forma, ma di sostanza applicativa.

Va notato che la stessa PR aveva prodotto tre finding di Gitleaks, tutti
risultati placeholder testuali. Lo strumento specializzato nella sicurezza ha
prodotto solo rumore, mentre il problema reale è stato colto dalla dimensione
di fairness: un esempio concreto di come dimensioni diverse intercettino
fenomeni diversi, e di perché una valutazione monodimensionale sia insufficiente.

### Perché non si riportano medie per agente

Con 949 PR su 1000 prive di eventi, le medie dei punteggi sarebbero tutte
prossime a 3,0 e le differenze tra agenti — determinate da pochi casi isolati
su 200 PR ciascuno — non sarebbero statisticamente significative. Riportarle
darebbe l'impressione di un pattern sistematico che i dati non supportano. Si
riporta perciò il **conteggio assoluto** degli eventi.

### Validazione manuale (accordo umano–judge)

La validazione ha coperto **70 PR**: tutte quelle con evento, più un gruppo di
controllo di PR neutre. La valutazione umana è stata condotta alla cieca, senza
vedere i punteggi del modello, applicando la stessa rubrica.

| Dimensione | accordo esatto | entro ±1 | correlazione |
|---|---|---|---|
| accessibilità | **100,0%** | 100,0% | 1,00 |
| linguaggio inclusivo | 94,3% | 95,7% | n/d |
| fairness demografica | 92,9% | 100,0% | 0,39 |
| overall_ethics | **45,7%** | 98,6% | 0,23 |
| **complessivo** | **83,2%** | 98,6% | — |

**Sulla composizione del campione.** Il 77% delle PR validate sono casi con
evento, contro il 5% del dataset complessivo: il campione è deliberatamente
concentrato sui casi difficili. Le percentuali di accordo sono quindi una
stima **conservativa**, e non sono confrontabili con quelle ottenute su
campioni prevalentemente neutri, dove l'accordo risulta meccanicamente più
alto per la semplice prevalenza del valore 3.

### Cosa mostra la validazione

**L'accessibilità è pienamente affidabile.** Accordo del 100% e correlazione
massima: su questa dimensione il giudizio automatico può essere usato senza
riserve.

**Le segnalazioni più severe sul linguaggio inclusivo non reggono.** I tre
disaccordi forti del campione riguardano tutti PR a cui il judge ha assegnato
punteggio 1 — il massimo allarme — dove la verifica umana ha rilevato
neutralità. La dimensione va trattata con cautela: il modello tende a
sovra-segnalare.

**`overall_ethics` non è una sintesi coerente.** Con il 45,7% di accordo esatto
è la dimensione meno affidabile, e il motivo è strutturale: il modello in alcuni casi assegna
valori non neutri anche quando tutte e tre le dimensioni sostanziali sono
neutre. Non essendo vincolata alle dimensioni che dovrebbe sintetizzare, non
può essere usata come indicatore autonomo — ed è la ragione per cui è stata
esclusa dalla definizione di evento.

---

## Sintesi trasversale

**Sustainability** offre il segnale più solido: OpenAI Codex produce il codice
più complesso per unità prodotta, con un margine che resiste al test di
robustezza. Il quadro resta però articolato, con profili di debolezza diversi
tra agenti.

**Subject Rights** si azzera dopo la validazione: nessun leak persistente, un
solo caso reale auto-corretto, 46 falsi positivi su 47 segreti univoci.

**IP Rights** non rileva conflitti né rimozioni di copyright, una volta esclusi
i file di lock e corretta la tabella di compatibilità.

**Fairness** individua 51 eventi su 1000 PR, in maggioranza miglioramenti
dell'accessibilità, e un solo caso sostanziale di logica potenzialmente
discriminatoria. La validazione mostra affidabilità piena sull'accessibilità e
limiti riconoscibili sulle altre dimensioni.

### Il contributo metodologico

**Tre dimensioni su quattro hanno prodotto risultati grezzi fuorvianti**, che
solo un intervento umano ha corretto:

- le metriche di complessità erano inquinate per il 38% da codice non scritto
  dagli agenti, al punto da **invertire** il confronto;
- il 98% dei finding di sicurezza si è rivelato rumore;
- i conflitti di licenza erano interamente generati da file di lock e da una
  tabella di compatibilità imprecisa.

In nessuno di questi casi lo strumento aveva sbagliato: Gitleaks ha
correttamente riconosciuto stringhe che *sembrano* segreti, Lizard ha
correttamente misurato la complessità dei file che gli sono stati dati,
ScanCode ha correttamente elencato le licenze che ha trovato. L'errore stava
nell'assumere che ciò che lo strumento misura coincida con ciò che si vuole
misurare. Il controllo umano non è un raffinamento accessorio della misura: è
parte costitutiva della misura.

---

## Limiti generali

- **Materiale di analisi eterogeneo.** Gitleaks e il judge di fairness lavorano
  sui diff, e sono quindi immuni al problema del recupero dei file. Lizard e
  ScanCode lavorano sui file completi, soggetti a una perdita contenuta e
  distribuita tra gli agenti.
- **Troncamento del diff nella valutazione di fairness.** Il diff inviato al
  modello è limitato a 100.000 caratteri; una minoranza di PR molto grandi
  resta troncata.
- **Numeri assoluti contenuti** per Gitleaks, ScanCode ed eventi di fairness:
  le differenze tra agenti sono descrittive, non prove statistiche.
- **Tabella di compatibilità delle licenze semplificata**, da sostituire con
  una matrice SPDX completa.
- **Sbilanciamento nella quantità di codice per agente**, mitigato dalla
  normalizzazione ma da tenere presente nell'interpretazione.
