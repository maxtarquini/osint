# Metodi di analisi e generazione dei grafi in Raven

**Fotografia del comportamento:** branch `dev`, 9 settembre 2026.

## Indice

- [Che cosa contiene il grafo](#che-cosa-contiene-il-grafo)
- [La base di integrità comune](#la-base-di-integrità-comune)
- [I tre metodi](#i-tre-metodi)
- [Evidence preparation](#evidence-preparation-comportamento-reale)
- [Dizionari](#dizionari-generici-modificabili-e-versionati)
- [Varianti e confronto A/B](#varianti-persistenti-attivazione-e-confronto-ab)
- [Recupero nella chat](#recupero-del-grafo-nella-chat)
- [Procedura operativa](#procedura-operativa-consigliata)
- [Limiti](#limiti-dimostrati-dalle-valutazioni)

## Scopo e risposta immediata

Raven trasforma i documenti di un’indagine in un grafo investigativo tracciabile. Il grafo non è
una rappresentazione della verità: raccoglie entità, proposizioni attribuite alle fonti, eventi,
confronti e citazioni, conservando l’incertezza necessaria a riesaminare il risultato.

L’applicazione offre tre metodi: **Affermazioni documentali**, **Verifica tra fonti** ed **Eventi e
temporalità**. Queste scelte hanno ancora senso. I metodi eseguono elaborazioni realmente diverse
e rispondono a domande diverse. Non formano però una scala crescente di qualità e nessuno dei tre
è risultato universalmente migliore nelle valutazioni disponibili.

Il precedente menu **Evidence preparation** è stato sostituito da **Originali con contesto
documentale**. Le tre opzioni `Compress Evidence`, `Full text` e `Translate + overlapping chunks`
fornivano già lo stesso input ai nuovi metodi: unità del testo originale con contesto documentale.
Ora la preparazione legacy non modifica neppure la firma usata per il riuso delle pagine dei
metodi selezionabili. I metadati delle varianti storiche rimangono invariati.

> **Modifica applicata il 9 settembre 2026**
>
> I tre metodi moderni mostrano una descrizione non selezionabile: **Originali con contesto
> documentale**. La preparazione richiesta resta nei metadati delle elaborazioni per consentire
> la lettura delle varianti storiche e dei percorsi di compatibilità. Una futura
> politica di preparazione potrà tornare selezionabile solo quando le alternative avranno
> semantica distinta, manifest esplicito e verifiche dedicate.

Questo manuale spiega il comportamento implementato sul branch `dev`, non i requisiti originari
né una proposta astratta. La fotografia tecnica principale è il rapporto di valutazione dell’8
settembre 2026, affiancato dal codice corrente.

## Una mappa mentale del sistema

Per usare correttamente la funzione occorre separare quattro decisioni che nell’interfaccia
possono sembrare vicine:

1. il **metodo investigativo** decide quali passaggi di analisi eseguire;
2. la **preparazione** è un parametro storico dell’acquisizione del testo;
3. la **variante** conserva un risultato specifico con input e versioni tracciati;
4. il **recupero per la chat** decide quale parte del risultato attivo entra nel contesto di una
   domanda.

La Figura 1 mostra che queste decisioni appartengono a fasi diverse.

```mermaid
flowchart TD
    D[Documenti originali] --> U[Unità citabili e contesto]
    V[Dizionario risolto] --> M[Metodo investigativo]
    U --> M
    M --> I[Controlli di integrità]
    I --> S[Snapshot della variante]
    S --> AB[Confronto A/B]
    S --> A[Selezione esplicita attiva]
    A --> R[Recupero per la chat]
    Q[Domanda utente] --> R
    R --> C[Risposta con variante e fonti]
```

*Figura 1 — Dal documento alla chat. La generazione produce una variante; solo una successiva
selezione la rende attiva. Il recupero della chat consulta quella variante senza rigenerarla.*

La distinzione evita due equivoci frequenti. Cambiare metodo non equivale a cambiare algoritmo
di ricerca per la chat. Generare una variante non equivale ad attivarla.

> **Lessico della pipeline**
>
> Uno **snapshot** è l’istantanea persistente di una generazione. Il **manifest** è la sua scheda
> tecnica: elenca parametri, input e versioni. Un **hash** è un’impronta del contenuto, utile a
> rilevare cambiamenti; non prova che il contenuto sia vero. Il **prompt** raccoglie le istruzioni
> date al modello. Un **batch** è un gruppo di unità elaborato in una singola chiamata al modello.

> **Concetto chiave — Che cos’è una variante**
>
> Una variante è uno snapshot immutabile di una generazione. Comprende il risultato e un manifest
> con documenti, hash, cataloghi, dizionario risolto, metodo, versioni dei prompt, modello e
> configurazione. Due varianti possono partire dagli stessi documenti e divergere per metodo,
> dizionario, configurazione o variabilità del modello. Il manifest rende input e versioni
> ispezionabili; non promette che una nuova esecuzione produca lo stesso output.

## Che cosa contiene il grafo

Il modello dati non si limita ai classici nodi e archi. Questa scelta è essenziale per non
ridurre una fonte complessa a relazioni binarie apparentemente certe.

### Entità e menzioni

Un’entità rappresenta una persona, organizzazione, luogo, documento o altro oggetto riconosciuto.
La classificazione deriva dal dizionario selezionato per l’indagine. Nome, tipo, sottotipo,
alias, identificatori esterni, citazioni e note di risoluzione rimangono disponibili per il
riesame.

Le menzioni estratte ricevono identificativi brevi durante l’analisi. Gli agenti indicano questi
identificativi anziché inventare UUID, cioè identificatori tecnici univoci e persistenti. Il
programma risolve poi i riferimenti. Questa procedura riduce gli estremi inesistenti che in
passato potevano invalidare un’intera lista di affermazioni.

La riconciliazione delle identità resta prudente. Un nome simile o un tipo appartenente alla
stessa famiglia può suggerire un confronto, ma non autorizza automaticamente la fusione. Il
rapporto tra due possibili identità rimane revisionabile.

### Affermazioni

Un’affermazione è una proposizione attribuita a una fonte. Contiene un soggetto, un predicato
canonico e, quando richiesto, un oggetto. Può anche contenere un valore letterale tipizzato, una
data, un intervallo di validità, qualificatori, una modalità, uno stato epistemico, una fonte
parlante e riferimenti ad altre affermazioni.

“Il rapporto afferma che A trasferì 240 EUR a B” non diventa automaticamente “A trasferì 240 EUR
a B ed è vero”. Raven conserva chi lo afferma, dove compare e come è stato interpretato.

I predicati canonici riducono differenze puramente lessicali. Per esempio, forme come
`DEPENDENCE` e `DEPENDS_ON` vengono ricondotte a `DEPENDENT_ON`; `TRANSFERRED` viene ricondotto a
`TRANSFER`. La normalizzazione conserva direzione, importo, valuta, periodo e scopo, perché
perdere uno di questi elementi cambierebbe la proposizione.

Il catalogo degli alias e la semantica dei predicati vivono nel codice, separati dai dizionari
di entità. Un predicato sconosciuto non viene scartato: rimane invariato, ma non acquisisce per
questo regole di confronto specializzate.

### Negazione, assenza e stato epistemico

La polarità indica se la fonte afferma o nega una proposizione. Lo stato epistemico distingue
`reported`, `not_documented` e `unknown`. La modalità distingue invece `asserted`, `alleged` e
`uncertain`: ipotesi e incertezza appartengono alla modalità, assenza di documentazione allo
stato epistemico.

Queste dimensioni non sono intercambiabili:

| Formulazione della fonte | Rappresentazione corretta | Errore da evitare |
| --- | --- | --- |
| “A appartiene a B” | relazione affermata | presentarla come verità accertata |
| “A non appartiene a B” | relazione negata | eliminare l’informazione dal grafo |
| “Non è documentato che A appartenga a B” | assenza di riscontro | trasformarla in una smentita |
| “La fonte ipotizza che A appartenga a B” | modalità `alleged` e attribuzione | promuoverla ad affermazione certa |

> **Attenzione — Assenza di evidenza**
>
> L’assenza di un riscontro nel materiale esaminato non prova che il fatto sia falso. Questo è un
> limite logico, non soltanto un dettaglio del software. Le prove RX41 mostrano che tutti i metodi
> confondono ancora alcuni casi di assenza con una smentita; la distinzione esiste nel modello ma
> l’estrazione non è infallibile.

### Rettifiche, ritiri e cessazioni

Una rettifica sostituisce o corregge il contenuto di un’affermazione precedente. Un ritiro revoca
una precedente ipotesi o attribuzione. Una cessazione descrive la fine temporale di una relazione
o attività. Sono operazioni differenti.

Il sistema può conservare riferimenti strutturati all’affermazione interessata e valori
temporali. Non è necessario inventare una seconda entità quando l’operazione ha un valore, una
data o un riferimento a un’altra proposizione.

La distinzione rimane delicata. Nella prova RX41 il ritiro di una localizzazione è stato
interpretato erroneamente come cessazione. Il modello dati consente la forma corretta, ma non
garantisce che il modello linguistico la scelga.

### Eventi e valori

Un evento è un record autonomo, specifico della fonte. Contiene un tipo, ruoli dei partecipanti,
affermazioni collegate, valori tipizzati, intervalli e provenienza. Record concorrenti non vengono
fusi silenziosamente.

Tutti i metodi possono ricavare un evento da un’affermazione che ne contiene gli elementi. Il
metodo temporale aggiunge un passaggio dedicato e amplia la copertura; non è l’unico modo in cui
nello snapshot può comparire un evento.

Un trasferimento può così essere rappresentato con mittente, destinatario, importo, valuta e
data. Una correzione da 93 a 39 CHF può mantenere entrambi i valori e il rapporto di rettifica,
anziché lasciare un singolo arco ambiguo.

### Archi proiettati

Gli archi mostrati nel grafo sono una proiezione operativa delle affermazioni positive che hanno
superato i requisiti previsti. La proiezione aiuta l’esplorazione visuale, ma contiene meno
informazione dell’affermazione completa.

Negazioni, assenze, ritiri e confronti possono quindi essere presenti nello snapshot pur non
apparendo come normali archi positivi. Per un’analisi accurata occorre consultare i dettagli delle
affermazioni e non dedurre la completezza dal solo disegno del grafo.

> **Concetto chiave — Proposta, non verdetto**
>
> Entità e affermazioni generate rimangono proposte. Anche una citazione letteralmente verificata
> e un giudizio semantico `supported` non certificano la verità della fonte né sostituiscono la
> revisione dell’analista.

## La base di integrità comune

I tre metodi condividono la stessa base moderna, registrata come versione di metodo 4 e prompt
`raven-integrity-v5`. La Figura 2 ne riassume il flusso.

```mermaid
flowchart TD
    P[Pagina originale] --> U[Unità contigue max 1.800 caratteri]
    U --> B[Batch target max circa 10.000 caratteri]
    P --> X[Contesto documentale entro budget]
    B --> E[Estrazione entità]
    X --> E
    E --> C[Estrazione affermazioni]
    C --> R[Validazione e riparazione limitata]
    R --> G[Citazioni originali]
    G --> S[Revisione semantica]
    S --> O[Consolidamento e confronti]
```

*Figura 2 — Base di integrità. Le citazioni provengono da unità contigue dell’originale; gli
elementi validi vengono conservati anche quando elementi fratelli richiedono riparazione.*

### Unità citabili e contesto

Il testo originale viene suddiviso in unità citabili contigue, lunghe al massimo 1.800 caratteri.
Gli offset si riferiscono ai caratteri dell’originale. Non si usano ellissi inventate né
corrispondenze approssimative per promuovere una citazione a verificata.

Le unità della pagina obiettivo vengono raggruppate in batch di circa 10.000 caratteri. Il
contesto proveniente dalle altre pagine è limitato dal budget applicativo di 32.000 caratteri e
serve a risolvere riferimenti, mentre le citazioni devono essere scelte dalle unità target.

Una pagina lunga può produrre più batch. Il budget di riparazione è applicato alla risposta di
estrazione del singolo batch; non va interpretato come un massimo fisso di riparazioni per
pagina.

### Validazione per elemento

Le risposte degli agenti usano uno schema strutturato. Ogni affermazione viene validata
separatamente: riferimenti alle menzioni, tipi dei campi, unità citate e vincoli dello schema
devono essere coerenti.

Se un elemento fallisce, la procedura tenta una riparazione limitata di quell’elemento. Gli
elementi validi della stessa risposta non vengono persi o sostituiti. Gli errori e le riparazioni
richieste rimangono nella diagnostica della pagina.

### I quattro livelli da non confondere

La pipeline conserva livelli distinti di controllo:

| Livello | Domanda | Che cosa dimostra |
| --- | --- | --- |
| Integrità strutturale | Il record rispetta schema e riferimenti? | Il dato può essere elaborato |
| Provenienza letterale | La citazione coincide con l’originale? | Le parole compaiono in quella fonte |
| Supporto semantico | La citazione sostiene la proposizione proposta? | Il revisore la ritiene coerente col testo |
| Verità e attendibilità | La fonte è corretta e indipendente? | Richiede analisi investigativa ulteriore |

Nel percorso moderno le citazioni selezionano unità originali con offset esatti. La normalizzazione
degli spazi appartiene al grounding di compatibilità del percorso precedente. Nessuno dei due
controlli decide se classificazione o proposizione siano corrette. Il revisore semantico può
respingere una proposta contraddetta dalla sua citazione, ma resta un giudizio del modello.

Lo `status` manuale (`proposed`, `verified`, `rejected`), il `semantic_support` del revisore e
l’attendibilità della fonte sono distinti. L’attendibilità nasce come `unassessed`: un esito
semantico positivo non la aggiorna automaticamente.

## I tre metodi

### Affermazioni documentali (`document_claims`)

È il metodo generale. Estrae dagli originali entità e proposizioni atomiche, usa il contesto del
documento per risolvere riferimenti, verifica provenienza e supporto e costruisce confronti
deterministici tra affermazioni compatibili.

È adatto come prima variante quando l’obiettivo è una mappa ampia del contenuto: chi o che cosa è
menzionato, quali relazioni sono attribuite alle fonti, quali valori e negazioni compaiono e dove
si trova il passaggio originale.

Il modello distingue tre famiglie di date: `asserted_at` è il momento in cui la fonte formula
l’affermazione; `valid_from` e `valid_until` delimitano il periodo descritto; `created_at` o la
data di generazione appartengono al record applicativo. Confonderle può trasformare la data di un
rapporto nella data dell’evento.

Non significa “analisi superficiale”. Applica tutta la base di integrità comune. Rispetto agli
altri metodi evita il passaggio dedicato agli eventi e la revisione mirata tra fonti, quindi tende
a produrre meno elaborazione aggiuntiva e meno candidati di confronto.

Nella prova RX41 ha prodotto 170 affermazioni, 62 archi positivi supportati dal modello e 14
confronti candidati in 71,4 minuti. Ha recuperato diversi scenari importanti, ma ha perso il
confronto completo sul trasferimento di 240 EUR e alcune dipendenze tra trascrizioni.

### Verifica tra fonti (`cross_source_review`)

Condivide l’estrazione documentale con il metodo precedente e aggiunge una revisione mirata dei
confronti tra fonti. Considera attribuzioni, dipendenza delle fonti, accordi, contraddizioni,
rettifiche e ritiri.

Il revisore non vota quale fonte abbia ragione. Classifica la relazione tra due proposizioni e
conserva esito e motivazione. Le coppie possono essere supportate, respinte, non correlate o
lasciate da revisionare.

I candidati vengono recuperati in blocchi mirati. Il revisore legge proposizioni, provenienza e
citazioni originali, poi conserva la coppia, registra esito e motivazione e può cambiare il tipo
del confronto. La motivazione mantiene traccia del tipo deterministico iniziale. Il metodo
temporale non esegue questo revisore tra fonti: il suo passaggio aggiuntivo riguarda eventi e
temporalità.

> **Concetto chiave — Documento e fonte non coincidono sempre**
>
> Un PDF è un contenitore e può riportare più fonti, ciascuna con il proprio `source_id`. Due PDF
> possono riprendere la stessa fonte, indicata tramite `derived_from`: non costituiscono
> automaticamente due conferme indipendenti.

Questo metodo è utile quando la domanda investigativa riguarda coerenza e genealogia delle
fonti: una notizia è indipendente, copiata, confermata, smentita o corretta? È anche opportuno
quando piccole differenze di predicato, tipo o qualificatore potrebbero nascondere un confronto.

La maggiore quantità di confronti non equivale a maggiore precisione. Su RX41 ha prodotto 165
affermazioni, 57 archi e 417 candidati in 114,5 minuti. Di questi, 266 sono stati giudicati non
correlati. Ha recuperato il confronto sul trasferimento di 240 EUR, ma non la dipendenza attesa
tra due trascrizioni e ha introdotto interpretazioni errate.

### Eventi e temporalità (`event_temporal`)

Aggiunge un secondo passaggio dedicato a eventi, transazioni, ruoli, valori, intervalli,
correzioni e cessazioni. È il metodo da preferire quando ordine e durata sono parte centrale della
domanda: che cosa è accaduto, quando, con quali partecipanti, quale valore è stato corretto e da
quale data una relazione non è più valida?

Il vantaggio è una rappresentazione più ricca. Il costo è una maggiore superficie di errore e
ambiguità. Lo stesso testo può generare più proposizioni e record evento senza diventare per
questo più corretto.

Su RX41 ha prodotto 266 affermazioni, 78 archi, 61 confronti e 60 eventi in 107,3 minuti. Ha
ricostruito bene alcuni intervalli e la rettifica di una data, ma ha duplicato un ritiro come
cessazione e ha introdotto dipendenze di fonte non sostenute.

### Come scegliere

La scelta deve seguire la domanda e il rischio informativo, non il desiderio di ottenere più nodi.

| Esigenza prevalente | Metodo iniziale consigliato | Motivo |
| --- | --- | --- |
| Inventario tracciabile di entità e proposizioni | Affermazioni documentali | Base ampia e più semplice da revisionare |
| Contraddizioni, copie, rettifiche tra fonti | Verifica tra fonti | Aggiunge revisione esplicita delle coppie |
| Cronologie, transazioni, valori e cessazioni | Eventi e temporalità | Modella ruoli, date, intervalli e valori |
| Caso ad alto rischio o ambiguo | Due o tre varianti da confrontare | Rende visibili recuperi e divergenze |

> **Esempio operativo**
>
> Se l’indagine riguarda un pagamento contestato, una variante documentale può offrire il quadro
> generale; una variante tra fonti può mettere in relazione affermazione e smentita; una variante
> temporale può conservare importo, valuta e intervallo. Il confronto delle tre non elegge un
> vincitore: aiuta l’analista a vedere elementi persi, interpretazioni discordanti e citazioni da
> rileggere.

## Evidence preparation: comportamento reale

Questa sezione chiude la verifica specifica delle opzioni mostrate nello screenshot
dell’interfaccia. Il comportamento è stato riscontrato nel percorso dalla TUI al servizio e nei
due analizzatori, moderno e legacy.

### Percorso moderno dei tre metodi

Quando si preme **Nuova variante**, la TUI passa al job il `method_id` e il valore di compatibilità
`full_text`, senza presentare una scelta di preparazione. Se è presente un metodo, il servizio
usa `IntegrityPageAnalyzer`.

L’analizzatore moderno riceve il parametro, ma non lo usa per preparare il testo. L’input è sempre
costruito dalle unità dell’originale. La lingua dell’indagine viene indicata come lingua delle
spiegazioni; nomi e contenuto citato restano nella forma originale. Non avviene una traduzione
preventiva della pagina.

Il manifest registra comunque `preparation_requested` e dichiara `extraction_basis="original"`.
Per i metodi selezionabili il profilo di cache esclude il primo campo e il piano pagina usa la
base effettiva `original`. Anche una chiamata di compatibilità che passi una modalità diversa
può quindi riusare pagine complete compatibili. Lingua, dizionario, modello, fonti e versioni
continuano a distinguere gli input. Il manifest salvato non viene modificato dalla normalizzazione.

| Valore legacy conservato | Effetto sui nuovi metodi | Effetto sulla cache dopo la modifica |
| --- | --- | --- |
| Compress Evidence | Nessuna compressione dell’input | Nessuna differenza dovuta a questo valore |
| Full text | Originali in unità e batch | Nessuna differenza dovuta a questo valore |
| Translate + overlapping chunks | Nessuna traduzione preventiva | Nessuna differenza dovuta a questo valore |

Questi tre valori non sono strategie distinte nel percorso moderno; per questo il menu è stato
rimosso. Le firme già salvate prima della modifica non vengono riscritte: il primo nuovo run
può rielaborare pagine con la vecchia firma. Il riuso successivo usa la firma corretta.

> **Diagnosi iniziale del 9 settembre 2026, prima della modifica**
>
> Un probe Python in memoria, con agente simulato e senza rete o database, ha eseguito le nove
> combinazioni tra tre metodi e tre preparazioni. Per ciascun metodo le tre modalità hanno fornito
> lo stesso input originale e non hanno invocato la funzione legacy di preparazione. Le modalità
> hanno però prodotto tre firme pagina differenti. Questa è una verifica del cablaggio e degli
> input, separata dalle generazioni LLM e dai benchmark dell’8 settembre.

Dopo la modifica, i test del servizio verificano il riuso fra tutte e tre le modalità legacy
per ciascun metodo, la conservazione dei manifest originali e la rielaborazione al cambio della
lingua. La verifica TUI comprende l'indicazione statica, la navigazione da tastiera e i formati
80×24 e 160×32. Il percorso legacy mantiene le proprie dipendenze di cache.

### Percorso legacy

Se il servizio viene chiamato senza `method_id`, usa `PageGraphAnalyzer`, il percorso precedente.
Qui tutte le modalità suddividono prima il testo in gruppi di parole. Solo `compress` esegue una
compressione distinta. Le altre due modalità seguono lo stesso ramo: se la lingua di analisi è
`ORIGINAL`, mantengono l’originale; altrimenti rilevano la lingua e possono tradurre quando è
diversa.

Di conseguenza anche nel legacy i nomi dell’interfaccia sono imprecisi: `Full text` non elimina la
segmentazione e `Translate + overlapping chunks` non è l’unica modalità che può tradurre.

Il legacy serve a leggere correttamente elaborazioni storiche e percorsi compatibili. Non deve
essere usato per dedurre il comportamento dei tre metodi moderni.

### Decisione applicata

Per i nuovi metodi, l’interfaccia mostra la base effettiva in forma informativa:
**Originali con contesto documentale**. I metadati delle varianti storiche conservano il valore
richiesto all’epoca, insieme alla versione del metodo e al manifest.

Se in futuro si introducono politiche reali di preparazione, ciascuna dovrà specificare almeno:
testo fornito all’estrattore, strategia di segmentazione, lingua, trattamento delle citazioni,
effetto sul riuso e versione. Solo allora un confronto A/B potrà attribuire differenze alla
preparazione con sufficiente chiarezza.

## Dizionari: generici, modificabili e versionati

I metodi sono indipendenti dal dominio. Il dizionario decide quali classificazioni di entità sono
ammesse e fornisce istruzioni di inclusione ed esclusione; non cambia la natura del metodo.

I vocabolari in formato JSON, una rappresentazione testuale strutturata dei dati, si trovano in
`config/osint-vocabularies`. Per impostazione predefinita Raven usa questa copia del progetto,
se disponibile, e altrimenti le risorse distribuite in `src/raven/resources/dictionaries`.
La cartella può essere scelta da
**Configuration > Dictionaries** o con `RAVEN_DICTIONARY_ROOT`. Un dominio selezionabile può
estendere definizioni comuni. Il loader valida schema, codici, versione semantica, ereditarietà,
limiti dimensionali e conflitti tra tipi.

I cataloghi documentali danno priorità, suggerimenti e contesto, ma non sostituiscono gli
originali e non escludono automaticamente pagine non catalogate.

> **Attenzione — Originale significa testo estratto**
>
> Quote e offset si riferiscono al testo estratto della pagina, non ai byte del PDF, alle
> coordinate grafiche o a un OCR certificato. OCR significa riconoscimento ottico dei caratteri:
> converte immagini di testo in testo elaborabile, ma può introdurre omissioni ed errori. Se
> parsing o scansione perdono contenuto prima della pipeline, né il catalogo né il grafo possono
> ricostruirlo con affidabilità.

All’inizio di ogni generazione Raven rilegge la cartella configurata e risolve il dominio
dell’indagine. Nelle nuove varianti, snapshot JSON completo, hash e versioni vengono fissati nel
manifest. Se un file cambia in seguito, una nuova variante usa le nuove definizioni. Gli snapshot
legacy privi delle definizioni complete conservano soltanto metadati e hash disponibili: Raven
non li completa usando retroattivamente il dizionario corrente.

Il sistema non è specializzato sul terrorismo. Quel dominio è una delle configurazioni
disponibili, insieme a domini generali, elettorali, marittimi, societari, energetici e altri. La
prova civile con museo, tipografia e importi in franchi è stata usata proprio per verificare che i
metodi non dipendessero dagli esempi RX41.

La modificabilità ha un confine preciso. I dizionari aggiungono o cambiano tipi, sottotipi e regole
di classificazione delle entità; non aggiungono automaticamente alias di predicati, nuova
semantica temporale o nuove strategie di confronto. La prova su un dominio civile dimostra una
capacità utile di generalizzazione, non la validità su ogni dominio possibile.

> **Attenzione — Il dizionario guida, non prova**
>
> La presenza di un tipo nel dizionario non dimostra che una menzione appartenga a quel tipo. La
> citazione deve sostenere la classificazione. Nella vecchia prova RX41, “Cellula Verde” era stata
> classificata come cellula terroristica benché la fonte la descrivesse come circolo di lettura:
> un esempio concreto del rischio di trattare il catalogo come evidenza.

## Varianti persistenti, attivazione e confronto A/B

### Generazione e manifest

Ogni generazione moderna crea una variante con un nuovo `run_id` e un nome facoltativo. Il
manifest conserva hash dei documenti, firme dei cataloghi, snapshot e hash del dizionario,
metodo e versioni, modello e configurazione.

Le pagine complete possono essere riutilizzate quando il profilo di estrazione è compatibile.
Le pagine parziali vengono rielaborate. `document_claims` e `cross_source_review` condividono il
profilo della fase documentale, mentre la revisione tra fonti viene rieseguita. Il metodo
temporale possiede un passaggio aggiuntivo e un profilo diverso.

Il riuso è un’ottimizzazione, non una prova di determinismo. Due varianti possono differire per
le pagine rielaborate e per la variabilità del modello.

### Apertura e attivazione

La schermata **Varianti / confronta** distingue tre azioni:

- **Apri A** visualizza una variante per consultazione;
- **Imposta attiva** la seleziona per l’indagine e per la chat;
- **Confronta** produce un rapporto tra A e B.

Una variante appena generata non diventa attiva automaticamente. Questo evita che un esperimento
sostituisca il grafo operativo. L’attivazione pubblica la proiezione esatta e poi registra in
MongoDB la variante scelta; MongoDB rimane l’autorità per la selezione.

Le proiezioni Neo4j sono isolate per coppia indagine-variante. Gli stessi identificativi possono
esistere in varianti diverse senza collisione. Le letture verificano anche l’appartenenza
all’indagine, impedendo di aprire per errore uno snapshot di un altro caso.

MongoDB conserva run, pagine e snapshot; Neo4j mantiene la proiezione per variante. Gli snapshot
precedenti restano leggibili tramite la compatibilità legacy. I dati correnti indicano schema 7
per MongoDB e proiezione 4 per Neo4j: numeri distinti dalla versione 4 del metodo.

### Confronto semantico

Il confronto non usa gli UUID casuali come equivalenza. Allinea entità per famiglia di tipo e
nome normalizzato, poi confronta proposizioni, valori, unità, precisione delle date,
qualificatori, attribuzioni, dipendenze delle fonti e riferimenti a rettifiche.

Valori numerici equivalenti come `39` e `39.00` vengono riconosciuti senza arrotondare numeri
lunghi. Unità diverse e date con precisione diversa non vengono confuse. Una diversa
segmentazione delle citazioni sulla stessa pagina non genera da sola una differenza.

Il rapporto evidenzia elementi presenti solo in A o B, classificazioni discordanti, cambi di
stato, confronti e giudizi semantici differenti. Non assegna un punteggio assoluto di qualità.
Per i dizionari distingue documenti identici da definizioni identiche e mostra definizioni
aggiunte, rimosse o modificate, anche quando codice e versione dichiarata non cambiano.

### Dati del grafo e disegno a schermo

La generazione stabilisce entità, affermazioni, eventi e relazioni; il layout decide soltanto dove
disegnarli. La vista usa un ordinamento Sugiyama per rendere leggibile la direzione, dispone le
componenti disconnesse su righe e può aggregare visivamente archi paralleli. I record sottostanti
restano distinti e consultabili.

La geometria non crea nuovi legami. Un nodo centrale, vicino o collocato in alto non è per questo
più attendibile o importante. Centralità, prossimità e forma del disegno sono aiuti di navigazione,
non evidenza investigativa.

> **Attenzione — Più nodi non significa grafo migliore**
>
> Un metodo può estrarre più record perché recupera dettagli utili, perché duplica lo stesso
> contenuto o perché introduce proposizioni ambigue. Senza un riferimento annotato e una rilettura
> delle fonti, il conteggio non misura accuratezza né completezza.

## Recupero del grafo nella chat

La chat usa la variante attiva, non quella semplicemente aperta. La risposta indica la variante
impiegata, rendendo riconoscibile il contesto investigativo.

Il recupero combina l’indice documentale Qdrant con il grafo attivo letto da Neo4j o dal fallback
esatto in MongoDB. La fusione dei ranking collega passaggi documentali, termini, entità, pagine e
affermazioni senza rigenerare il grafo. I confronti significativi possono richiedere che due
affermazioni entrino
insieme nel contesto. Sono ammessi a questo raggruppamento gli esiti supportati o ancora non
revisionati di tipi investigativamente utili, come accordo, contraddizione, cambiamento temporale,
dipendenza, rettifica, ritiro o cessazione.

L’indice RAG documentale è separato e può essere condiviso da varianti compatibili. RAG significa
*Retrieval-Augmented Generation*: la risposta viene costruita fornendo al modello materiale
recuperato dagli indici. La generazione del grafo non ne sovrascrive lo stato: “grafo completato”
e “documento indicizzato” sono condizioni indipendenti.

Confronti respinti, non correlati o irrisolti rimangono nello snapshot per la revisione, ma non
allargano automaticamente i gruppi di contesto. Questa correzione ha impedito che centinaia di
coppie irrilevanti consumassero il budget e facessero perdere il confronto sui 240 EUR.

Il massimo applicativo verificato per il contesto del grafo è 24.000 caratteri. Budget dinamici
inferiori possono ancora escludere un intero gruppo. Il recupero decide che cosa viene mostrato al
modello di chat; non corregge un’estrazione errata e non dimostra che una risposta LLM sia corretta.

La Figura 3 chiarisce il confine.

```mermaid
flowchart TD
    G[Variante attiva completa] --> Q{Termini, pagine e documenti}
    Q --> K[Entità e affermazioni candidate]
    K --> J[Gruppi di confronti significativi]
    J --> B{Budget disponibile}
    B -->|entra| C[Contesto della chat]
    B -->|non entra| O[Record resta nella variante]
```

*Figura 3 — Recupero per la chat. L’esclusione dal contesto di una domanda non cancella il record
dalla variante e non equivale a un rigetto investigativo.*

## Procedura operativa consigliata

Prima della generazione, verificare che i documenti appartengano all’indagine, che gli hash siano
coerenti e che il dominio del dizionario sia quello desiderato. Scegliere poi il metodo in base
alla domanda principale, assegnando alla variante un nome che renda riconoscibili scopo e ipotesi,
per esempio `base-documentale-2026-09` o `cronologia-pagamenti-v1`.

Durante l’elaborazione, osservare stato, pagina e diagnostica. “Parziale” non significa
necessariamente inutile: può indicare che alcuni elementi sono stati conservati e altri hanno
fallito validazione o riparazione. Un numero elevato di pagine parziali richiede comunque una
revisione della copertura.

Le chiamate lunghe hanno timeout configurato e annullamento cooperativo. Un annullamento conserva
lo stato `cancelled`; un errore registra fase e diagnostica senza attivare un risultato incompleto.
La TUI impedisce invii duplicati mentre il job è in corso.

Al termine, aprire la variante senza attivarla. Controllare prima citazioni e proposizioni negli
scenari decisivi, comprese negazioni, assenze, valori e date. Esaminare poi confronti e dipendenze
delle fonti. Solo dopo questa revisione scegliere se impostarla come attiva.

Quando il rischio è alto, generare una seconda variante con il metodo più adatto al dubbio
residuo. Nel confronto A/B cercare differenze sostanziali: elementi persi, oggetti diversi,
qualificatori mancanti, rettifiche non collegate e giudizi semantici discordanti. Non scegliere in
base al totale di nodi o archi.

Infine porre alla chat domande circoscritte e verificare che la risposta indichi la variante
attiva. Per conclusioni importanti, tornare sempre alle citazioni originali.

## Limiti dimostrati dalle valutazioni

Le prove disponibili comprendono il corpus sintetico RX41 e un corpus civile indipendente dagli
esempi dei prompt. Sono valutazioni controllate e assistite, non un benchmark annotato da più
valutatori umani indipendenti.

Su RX41, i tre metodi hanno conservato complessivamente 601 affermazioni e 492 confronti. Tutti i
1.990 intervalli di record coincidevano con gli originali. Lo stesso passaggio può comparire in
più record: non sono 1.990 passaggi unici. Il risultato dimostra la provenienza letterale degli
intervalli, non la correttezza delle proposizioni.

| Metodo | Affermazioni | Archi positivi supportati | Confronti | Tempo |
| --- | ---: | ---: | ---: | ---: |
| Affermazioni documentali | 170 | 62 | 14 | 71,4 min |
| Verifica tra fonti | 165 | 57 | 417 | 114,5 min |
| Eventi e temporalità | 266 | 78 | 61 | 107,3 min |

Nessun metodo ha superato tutti gli scenari. Tutti hanno recuperato la classificazione civile di
Cellula Verde, il confronto sulla dipendenza di Cerchio Grigio, il ritiro dell’identità Prisma e
la correzione di una data. Tutti hanno gestito solo parzialmente alcune assenze, ritiri e ambiti.
Nessuno ha ricostruito la dipendenza attesa tra le trascrizioni NI-01 e RI-02.

Nel corpus civile, il metodo temporale ha recuperato più aspetti di prezzi, date e cessazioni, ma
ha prodotto anche più proposizioni ambigue. Il metodo tra fonti ha riconosciuto una copia e una
cessazione, ma non ha recuperato correttamente l’assenza di evidenza. Il metodo documentale ha
offerto una base più contenuta, lasciando incompleti alcuni rapporti temporali.

I principali limiti operativi sono quindi:

- errori semantici anche tra record marcati `supported`;
- confusione residua tra negazione e assenza di riscontro;
- ritiri rappresentati come cessazioni;
- attribuzioni incomplete o con soggetto errato;
- dipendenze tra fonti perse o inventate;
- copertura variabile tra pagine e tra generazioni;
- gruppi di recupero ancora soggetti al budget della chat.

Questi limiti non rendono inutili le opzioni di metodo. Definiscono il loro ruolo corretto: sono
strumenti per produrre proposte tracciabili e prospettive complementari, da confrontare e
revisionare.

## Domande frequenti

### Qual è il metodo più accurato?

Le prove non individuano un vincitore universale. L’accuratezza dipende dal tipo di informazione
e dal singolo scenario. Per una cronologia il metodo temporale può recuperare dettagli aggiuntivi;
per le dipendenze tra fonti è più pertinente la verifica tra fonti; per una prima mappa è spesso
più leggibile il metodo documentale.

### Posso fidarmi di una citazione verificata?

Puoi fidarti del fatto che il passaggio coincide con l’originale nei limiti del controllo
eseguito. Non puoi dedurne automaticamente che la proposizione sia una corretta parafrasi, che la
classificazione sia giusta o che la fonte dica il vero.

### Perché una negazione non appare come arco?

Gli archi ordinari sono una proiezione positiva e supportata. La negazione rimane tra le
affermazioni e nei confronti, dove conserva fonte, ambito e citazione. Consultare soltanto la
vista degli archi elimina proprio l’informazione necessaria a capire una controversia.

### Modificare il dizionario cambia le vecchie varianti?

Una nuova generazione rilegge il dizionario e le nuove varianti conservano snapshot, hash e
versioni delle definizioni usate. Le varianti legacy possono avere solo i metadati disponibili;
non vengono reinterpretate silenziosamente usando le definizioni correnti.

### Perché una nuova variante non compare subito nella chat?

La generazione e l’attivazione sono separate intenzionalmente. Apri e revisiona la variante, poi
usa **Imposta attiva**. La chat continuerà a usare la variante attiva precedente fino a quella
scelta esplicita.

### Ha senso confrontare due run con lo stesso metodo?

Sì, purché si legga il manifest. Il confronto può mostrare l’effetto di un dizionario aggiornato,
di documenti diversi o della variabilità del modello. Non attribuisce però automaticamente la
differenza a una singola causa.

## Riferimenti tecnici annotati

> **Riferimento essenziale — Valutazione reale**
>
> [Varianti investigative e verifica delle fonti](research/graph-evaluation-2026-09-08.md)
> documenta le generazioni RX41 e civili, i risultati per scenario, la persistenza e i limiti.
> È la fonte principale per i numeri riportati qui. Le prove sono controllate e sintetiche: non
> rappresentano una stima generale dell’accuratezza su corpus OSINT reali.

> **Riferimento essenziale — Contesto di implementazione**
>
> [Handoff dell’implementazione](research/graph-implementation-handoff-2026-09-08.md) descrive i
> difetti osservati prima della revisione e gli obiettivi dell’intervento. È utile per comprendere
> perché esistono integrità, varianti e metodi distinti, ma le sue sezioni prescrittive non sono la
> prova del comportamento corrente.

Il registro è in [metodi](../src/raven/graph/methods.py); affermazioni, eventi e manifest sono nei
[modelli](../src/raven/models/graph.py). La pipeline moderna è in
[integrità](../src/raven/graph/integrity.py) ed è orchestrata dal
[servizio di analisi](../src/raven/services/graph_analysis.py).

Alla data del manuale il codice dei predicati dichiara `raven-predicates-v2`, mentre la
configurazione serializzata nel manifest registra ancora `raven-predicates-v1`. Questa discrepanza
riduce la precisione descrittiva del manifest e va considerata quando si ricostruiscono gli input
storici di una variante.

Confronto e proiezione sono in [claims](../src/raven/graph/claims.py); l’allineamento A/B è in
[variants](../src/raven/graph/variants.py). Le regole dei dizionari sono in
[vocabulary](../src/raven/graph/vocabulary.py); il contesto della chat è coordinato da
[retrieval](../src/raven/services/retrieval.py) e [chat](../src/raven/services/chat.py).

I riferimenti al codice descrivono il branch `dev` alla data di questo manuale. Per verificare un
risultato specifico, il manifest della variante e la citazione originale rimangono i riferimenti
operativi più importanti.
