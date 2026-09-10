# Raven OSINT

Raven is a keyboard-first Python TUI for creating transparent, LLM-assisted OSINT
knowledge graphs. The current foundation provides a responsive home screen, infrastructure
bootstrap, connection monitoring, investigation creation, isolated evidence knowledge bases,
and non-secret endpoint configuration.

## Requirements

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/) (recommended)
- MongoDB, Qdrant, and Neo4j instances reachable from the machine running Raven
- One optional AI provider: vLLM, llama.cpp, Ollama, or OpenAI
- A terminal of at least 80×24 for the complete ASCII logo; narrower terminals use a compact
  fallback automatically

## Run

```bash
uv sync
uv run raven
```

You can also launch the package directly:

```bash
uv run python -m raven
```

On startup Raven checks the three data services and the shared AI node concurrently. A successful
first data-service connection creates
the base structures idempotently:

- MongoDB database `raven`, with `investigations`, `evidence_documents`, `sources`, `entities`,
  `relationships`, `graph_checkpoints`, `graph_analysis_runs`, `chat_messages`, and
  `app_metadata` collections plus their base indexes;
- Qdrant collection `raven_documents`, using cosine distance and 1536-dimensional vectors;
- Neo4j constraints for investigations, entities, sources, and schema metadata, plus entity name
  and type indexes.

The Evidence storage root, database names, endpoints, Qdrant collection, vector size, and the
application-wide inference and embedding nodes are configurable independently from the
`Configuration` menu. Both support `vllm`, `llama.cpp`, `ollama`, and `openai`; Raven checks that
each selected model is exposed before becoming ready. Inference settings also include thinking
effort, Top K, random seed, timeout, and context budget. Public
settings are written atomically to the operating system's user configuration directory. Neo4j and
AI credentials are never written to that JSON file. The Neo4j password is persisted in the
operating system credential vault; AI API keys entered in the TUI remain session-only.

Use `Test nodes` in the fixed configuration action bar to probe both draft providers, endpoints,
credentials, and models without saving or replacing the active nodes.

## Investigations and evidence

`Investigations` in the top menu opens the persisted investigation catalog. The catalog supports
name/context search, sorting by last update or name, manual refresh, and displays status, last
update, and evidence count for every investigation. Use `Open` to enter its workspace or
`New investigation` to start a new one.

`Start a new investigation` opens a keyboard-accessible form for:

- the investigation name and optional context;
- the default operational analysis language (`Original`, Italian, English, French, Spanish,
  German, or Arabic);
- one named-entity analysis domain loaded from the configured dictionary folder;
- one or more investigation questions.

After creation Raven opens the investigation workspace. Its `Evidence` tab provides a
compact keyboard-accessible filesystem picker, with shortcuts for the home directory, project
workspace, and parent directory. Evidence management is independent from investigation creation.

Accepted formats are PDF, Word (`.doc`, `.docx`), and Markdown (`.md`, `.markdown`), with a
100 MiB limit per file. Every uploaded row shows the filename, format, page count, ingestion state,
and a `Delete` button with explicit confirmation. PDF and Word page metadata are used when
available; estimated counts are prefixed with `~`, while unavailable legacy metadata is shown as
`N/D`.

Raven copies each document into `<configured-root>/<investigation-id>/`. The root is configured in
`Configuration > Storage` (or with `RAVEN_EVIDENCE_ROOT`), and the investigation workspace always
shows the effective destination. Raven creates the investigation subfolder when the case is
created. Changing the configured root does not move copies already stored under another root.
Original filenames, media types, formats, sizes, SHA-256 hashes, page metadata, storage keys, and
`pending` ingestion states are registered in MongoDB's `evidence_documents` collection. Deleting
evidence removes the Raven-managed copy and metadata but never modifies the original source file.

The graph details sidebar starts at 30% of the available width. Drag the `↔` divider
between the graph and details to adjust their sizes. You can also focus the divider with
`Tab`, use `Left` / `Right` to resize, and press `Home` or double-click to restore the default.
Both panes retain a usable minimum width. The chosen proportion is retained while switching
tabs and resizing the terminal within the current workspace.

The Evidence list verifies the RAG index in Qdrant when opening the workspace. `Indexed`
means its signature matches the current document, language, and index format; `Da aggiornare`
means an index exists but needs refreshing with `Reindicizza`. `Non verificato` means Qdrant
could not be checked. This check runs no models and does not alter stored documents or vectors.
Graph extraction failures remain in graph runs and page coverage; they never change RAG status.

## Evidence-to-Graph analysis

Il [manuale dei metodi di analisi e generazione dei grafi](docs/graph-analysis-methods.md)
descrive in italiano gli algoritmi, il workflow degli agenti e le loro responsabilità, i prompt
effettivi e il ruolo delle skill, oltre a dizionari, varianti, confronto, recupero per la chat e
limiti verificati. È disponibile anche in [PDF](output/pdf/graph-analysis-methods.pdf).
Il precedente menu **Evidence preparation** è
sostituito dall'indicazione **Originali con contesto documentale**: i tre metodi selezionabili
usano gli originali e ignorano la preparazione legacy anche nella firma della cache.

In **Graph**, choose **Nuova variante** or **Varianti / confronta**. Select the investigative
method and an optional name before generation. The method becomes the default for the case;
its purpose, version and model are shown in the dialog. Each completed generation creates a
persistent variant. Use **Apri A** to inspect one, **Confronta** for A/B, and **Imposta attiva**
to explicitly select the graph used by chat. Opening or generating a variant does not activate it.

| Method | Investigative behavior |
| --- | --- |
| Affermazioni documentali | Original pages, document context, attributed propositions and semantic support review |
| Verifica tra fonti | Shared document extraction plus targeted comparison of source scope, disagreement, copies and corrections |
| Eventi e temporalità | Document extraction plus a dedicated pass for events, typed values, corrections, withdrawals and cessations |

The methods extract from originals, shown as **Originali con contesto documentale**. Catalogs can
prioritize pages but cannot exclude them or supply quotations. Program-assigned mention IDs
and contiguous citation units constrain model references. Validation preserves valid siblings;
claim repairs are bounded to one attempt per extraction batch. Source pages, model stages,
elapsed time, cancellation and diagnostics remain visible during the run.

Literal quotation matching and semantic support are separate. The supported graph only projects
grounded affirmative relations whose semantics passed review. **Affermazioni / copertura** keeps
all source assertions, including denials and absence of documentation; **Da revisionare** preserves
unsupported candidates, and **Eventi / tempo** exposes source-specific event records. A semantic
review does not certify the truth or reliability of a source, and can also misinterpret its
meaning. The [controlled evaluation](docs/research/graph-evaluation-2026-09-08.md) records
recovered cases, omissions and reviewer errors on RX41 and an independent civil corpus.

MongoDB snapshots preserve the immutable manifest: document hashes, catalog and dictionary
versions, method and prompt versions, model and public configuration. Neo4j projections are
partitioned by case and variant, including when they contain identical entity/claim IDs. Legacy
snapshots remain readable without being rewritten. A/B aligns candidate identities and qualified
propositions, showing recovered/missing assertions, classification differences, source coverage
and fragmentation; the counts are not an accuracy score. Equivalent numerical representations
align without rounding long values; units and date precision remain distinct. Attribution,
copy ancestry and correction references participate in alignment. References to claim IDs
resolve to their propositions within each variant; differing reviewer outcomes are shown
with both rationales even when the underlying proposition aligns.
Rejected, unrelated and unresolved comparison candidates remain available for review, but do
not force claims into joint chat-context groups. Meaningful comparison candidates retain both
sides together, and the chat receives their review states and rationales.

The graph view uses `netext`'s native Textual widget with a deterministic left-to-right
Sugiyama layout. It supports mouse selection, arrow-key panning, `J/K` entity navigation,
`+/-` zoom, `0`/`Fit` readable fit, level-of-detail rendering when zooming out, entity search,
directed relationship labels, and an Evidence/provenance detail panel. Multiple relationships
between the same pair are aggregated visually without discarding their underlying records.

Disconnected components are arranged in rows while preserving the directed layout inside each
group. `Fit` keeps entity names readable; larger graphs extend into the scrollable area rather
than collapsing into anonymous dots. Use the arrows to pan, entity search or `J/K` to reach a
node, and `+/-` for a manual overview. No relationships are added by this visual arrangement.

The selected quality methods report an unavailable AI node as a failed analysis; the legacy
compatibility pipeline can still extract deterministic observables. Agent failures never
turn unsupported statements into verified facts: extracted graph items are stored as `PROPOSED`.
Every new generation reloads the configured dictionary files, including edits made while Raven
is open. Extraction and semantic review use the same resolved definitions, including custom
types and their inclusion/exclusion rules. The resulting snapshot remains fixed during that run.
Changing definitions or versions changes the cache signature; previously saved variants retain
their original classification data, resolved dictionary definitions and manifest. A/B comparison
distinguishes identical documents from identical dictionaries and shows added, removed or changed
definitions. Older variants without a saved definition snapshot are identified explicitly.

Every run freezes the investigation language, preparation mode, dictionary domain, component
versions, and dictionary snapshot hash for reproducibility. The eleven copied Hudiny dictionaries
live in `config/osint-vocabularies`; domains remain separate and are never globally overlaid.
The `Overview` tab can edit the case brief, questions, reference/normalization language, and
dictionary domain. Changing language or domain retires legacy derived graph data and marks
Evidence for reprocessing; named variants retain their original manifest and the source documents
remain untouched. `GENERAL_OSINT` is used for legacy cases
and as the creation-form default. The same tab provides a confirmed investigation deletion flow
that removes Raven's Evidence directory, MongoDB records, chat history, Qdrant partition, and
Neo4j subgraph without modifying the original source files.
Qdrant remains the derived semantic-document index and is not used as the source of truth for graph
facts.

## Investigation chat and RAG

Every workspace has a `Chat` tab scoped to that investigation. On the first question, or with
`Index RAG`, Raven extracts the immutable Evidence copies, creates overlapping paragraph-aware
chunks within each physical page, preserves the original text, normalizes a copy into the
investigation's reference language when one is selected, obtains
embeddings from the configured embedding model, and idempotently upserts them to Qdrant. A
mandatory `investigation_id` payload filter isolates retrieval between cases. Documents are
reindexed when their SHA-256, normalization language, or page-index format changes; deleted documents have
their vectors removed.

Each chat request receives:

- the most relevant Evidence chunks with stable `[E1]`, `[E2]`, … citation labels;
- a question-directed subset of the current graph, including complete comparison groups,
  entity/relationship provenance, confidence, and status;
- the investigation brief, questions, language, and dictionary domain;
- up to twelve recent turns from the MongoDB-backed conversation history.

Responses stream token by token through Textual's incremental Markdown renderer. Fenced
`mermaid` blocks are upgraded after the stream completes to themed, terminal-native Unicode
diagrams using the MIT-licensed `termaid` renderer, with independent horizontal scrolling for
wide diagrams. `Ctrl+Enter` sends, `Cancel` stops after the active provider event, and clearing
history requires explicit confirmation.

The composer also handles case-insensitive local commands without calling the model:

- `/NEW` confirms and clears the persisted conversation history;
- `/SAVE` asks for a folder and filename, then creates a new `.md` export of the latest model
  response and its sources without overwriting an existing file;
- `/STATS` displays saved-message, token, RAG, Evidence, and graph counts;
- `/INFO` displays the active language/domain, inference and embedding context, Evidence files,
  graph snapshot, and latest answer citations.

The interaction design follows Toad's stream-first Markdown conversation model. Raven does not
embed or copy the `batrachian-toad` package: current Toad releases are a complete AGPL application
requiring Python 3.14 and a pinned Textual runtime, which is incompatible with Raven's proprietary
Python 3.12+ package. This keeps the implementation license-safe while preserving the requested
Toad-style experience.

## Credentials and endpoint overrides

Copy `.env.example` as a reference and export secrets in the process environment:

```bash
export RAVEN_MONGODB_URI='mongodb://username:password@localhost:27017'
export RAVEN_EVIDENCE_ROOT='/path/to/raven-evidence'
export RAVEN_DICTIONARY_ROOT='/path/to/osint-dictionaries'
export RAVEN_QDRANT_API_KEY='...'
export RAVEN_NEO4J_PASSWORD='...'
export RAVEN_AI_PROVIDER='ollama'
export RAVEN_AI_MODEL='qwen3'
export RAVEN_AI_THINKING='medium'
export RAVEN_EMBEDDING_PROVIDER='ollama'
export RAVEN_EMBEDDING_MODEL='nomic-embed-text'
uv run raven
```

Supported variables:

- `RAVEN_MONGODB_URI`
- `RAVEN_EVIDENCE_ROOT`
- `RAVEN_DICTIONARY_ROOT`
- `RAVEN_QDRANT_URL`
- `RAVEN_QDRANT_API_KEY`
- `RAVEN_NEO4J_URI`
- `RAVEN_NEO4J_USERNAME`
- `RAVEN_NEO4J_PASSWORD`
- `RAVEN_AI_PROVIDER`
- `RAVEN_AI_BASE_URL`
- `RAVEN_AI_MODEL`
- `RAVEN_AI_API_KEY`
- `RAVEN_AI_THINKING`
- `RAVEN_AI_TOP_K`
- `RAVEN_AI_RANDOM_SEED`
- `RAVEN_AI_TIMEOUT_SECONDS`
- `RAVEN_AI_CONTEXT_SIZE`
- `RAVEN_EMBEDDING_PROVIDER`
- `RAVEN_EMBEDDING_BASE_URL`
- `RAVEN_EMBEDDING_MODEL` (legacy alias: `RAVEN_AI_EMBEDDING_MODEL`)
- `RAVEN_EMBEDDING_API_KEY`
- `RAVEN_EMBEDDING_TIMEOUT_SECONDS`

`RAVEN_NEO4J_PASSWORD` takes precedence over the password stored by the TUI in the operating
system credential vault. This provides a non-interactive option for servers and containers where
a desktop keychain is unavailable.

## Navigation

The top menu exposes `Home`, `Investigations`, and `Configuration`. `Investigations` opens the
catalog, while the primary home action starts the creation workflow directly. Graph execution
remains a later step.

- `c` opens configuration;
- `r` checks all infrastructure services again;
- `?` opens contextual help;
- `q` exits Raven;
- `Enter` activates the focused control;
- `Esc` closes dialogs or returns home.

Each connection indicator combines an LED-like symbol with `Checking`, `Connected`,
`Configure node`, `Auth required`, or `Unavailable`, so the state never depends on color alone.
Detailed driver errors are kept in the user-local Raven log and are not rendered in the normal
TUI.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

The Python package uses a `src` layout. Presentation code lives under `raven.tui`; configuration,
services, and persistence adapters remain outside UI callbacks.

Before adding components, review the quality gates in [`dev-guides`](dev-guides/), especially
[`TUI_DEVELOPMENT_GUIDELINES.md`](dev-guides/TUI_DEVELOPMENT_GUIDELINES.md).


## Registro di skill e tool

Il pulsante **Cataloghi** nella navigazione principale e il tasto **S** dalla home aprono
la schermata **Cataloghi · Skills e Tools**. Puoi cercare e filtrare per disponibilità,
disabilitazione o necessità di verifica. **Tool usati** mostra le dipendenze dichiarate;
**Tutti i tool** ripristina l'elenco completo. Le schede dei tool mostrano le skill che li
usano, le modalità di accesso ai dati e gli schemi di chiamata MCP e locali.

In **Configurazione → Skills & Tools** puoi scegliere la cartella dei file `.SKILL`.
Il valore viene applicato salvando la configurazione; `RAVEN_SKILL_ROOT`, quando presente,
ha la precedenza. La cartella predefinita è `skills` nella directory dati di Raven.
Cambiare cartella non sposta i file già presenti. **Gestisci** apre il registro che usa
la configurazione salvata: le modifiche ancora nel modulo non vengono applicate al registro.

La schermata **Cataloghi** separa le skill dai tool. Una skill è una definizione di lavoro
investigativo, scritta in Markdown con un contratto iniziale; un tool è un'operazione
implementata nel programma. **Aggiungi esempi** installa sei definizioni: catalogazione
pagine, estrazione di entità e relazioni, riconciliazione delle identità, analisi delle
contraddizioni, ricostruzione cronologica e risposte con citazioni. L'installazione conserva
i file già presenti. Ogni esempio include metodo, limiti e un caso di test con risultato
atteso. I casi descritti nei file sono specifiche per la futura esecuzione della skill,
non risultati di un workflow già eseguito.

**Nuova .SKILL** apre un modello modificabile. **Modifica** permette di aggiornare il file
selezionato; `Ctrl+S` convalida e salva. `Invio` sulla tabella porta il fuoco alla consultazione,
dove sono disponibili il testo completo e l'eventuale scheda AI. Il filtro cerca anche nel
contenuto delle skill e nel catalogo. **Abilita/Disabilita** controlla la disponibilità nel
registro, senza avviare analisi.

Il file UTF-8 deve iniziare con un blocco JSON, seguito dalle istruzioni Markdown.
L'estensione è `.SKILL`, maiuscola. Questo è un esempio minimo valido:

````markdown
```json
{
  "id": "verifica-citazioni",
  "name": "Verifica delle citazioni",
  "version": "1.0.0",
  "description": "Verificare che una citazione compaia nella pagina indicata.",
  "inputs": ["Documento, pagina e citazione proposta"],
  "outputs": ["Esito della verifica con provenienza"],
  "tools": ["read_page", "verify_quote"]
}
```

# Metodo

Leggi la pagina e verifica la citazione esatta. Riporta documento, numero di pagina
ed esito. Non trasformare una parafrasi in una citazione.

## Limiti

La corrispondenza testuale non dimostra la verità dell'affermazione citata.

## Caso di test

Se la pagina riporta «240 euro» e la citazione proposta dice «250 euro»,
il risultato atteso è una verifica negativa.
````

> **Identità e versione.** `id` è l'identificatore stabile della skill e deve essere unico
> nella cartella. `version` usa tre numeri, per esempio `1.0.0`. `inputs` e `outputs`
> descrivono ciò che serve e ciò che deve essere prodotto; `tools` contiene gli identificatori
> esatti delle operazioni richieste. Il registro accetta al massimo 500 file, di 32 KiB
> ciascuno. File non validi, identificatori duplicati e tool indisponibili vengono segnalati.
> Una modifica esterna intervenuta dopo l'apertura dell'editor impedisce il salvataggio,
> così una versione più recente non viene sovrascritta per errore.

**Catalogo AI** usa `SkillCatalogAgent` e il modello configurato in AI Node per descrivere
ogni skill: scopo, condizioni d'uso, esclusioni, metodo e temi. La richiesta ha uno schema
JSON vincolante, un massimo di 2048 token e un limite di 120 secondi, ulteriormente ridotto
se il nodo ha un timeout inferiore. Durante il lavoro vengono mostrati skill corrente,
avanzamento e tempo trascorso; **Annulla** interrompe il lavoro conservando le schede già
salvate. La risposta di una richiesta già inviata viene scartata dopo l’annullamento;
la chiamata HTTP in corso termina alla risposta o al timeout. Errori di connessione,
autenticazione e timeout fermano il lotto lasciando le altre skill da catalogare.
Un nuovo avvio riprende le schede mancanti, fallite o da aggiornare.

> **Descrizione e autorizzazione.** La scheda AI è un aiuto alla selezione, non una concessione
> di permessi. Il programma conserva il contratto dichiarato nel file e non consente al modello
> di aggiungere tool. Il contenuto della skill viene analizzato come dato dal catalogatore:
> non viene eseguito. Il catalogo registra versione, impronta SHA-256, agente, modello e data;
> cambiamenti al file o al profilo del catalogatore rendono la scheda da aggiornare.

Il registro comprende ora **18 tool investigativi** condivisi con il server MCP `stdio`.
Per consultarli da un client esterno usa `uv run raven-mcp --investigation UUID`; il parametro
è obbligatorio e ripetibile. Sono disponibili fonti originali, recupero ibrido, entità,
affermazioni, relazioni, eventi, copertura, dizionari e confronto delle varianti persistenti.
I tool rispettano le abilitazioni configurate in Raven e non attivano o generano varianti.
Il [manuale dei tool e del server MCP](docs/tools-and-mcp.md) descrive contratti, avvio,
paginazione, provenienza, limiti e verifiche riproducibili.

La scheda **Tools** mostra versione, descrizione, perimetro, timeout e schemi di input/output.
I primi tool sono `read_page`, `search_evidence` e `verify_quote`. L'esecutore lavora su uno
snapshot di pagine originali che il chiamante autorizzato ha preparato per una sola indagine:
non legge percorsi arbitrari, non chiama servizi esterni e non modifica il grafo. Verifica
permessi, stato abilitato, argomenti e appartenenza di tutte le pagine all'indagine prima di
produrre risultati. La ricerca è letterale, senza distinzione tra maiuscole e minuscole,
con al massimo 20 risultati; la verifica della citazione è invece esatta. Ogni risultato
porta gli identificatori di indagine, documento e pagina. I tool accettano al massimo 2000
pagine da 100.000 caratteri ciascuna e applicano un limite cooperativo di cinque secondi.
Nuove implementazioni di tool richiedono codice e test: un file `.SKILL` non può installare
codice eseguibile.

Il catalogo e le preferenze sono salvati atomicamente in `.raven-capabilities.json` nella
cartella delle skill. **Esporta** genera `raven-discovery-catalog.json`, con le sole skill
valide, abilitate, aggiornate e dotate di tool disponibili, oltre ai contratti dei tool
abilitati. L'esportazione è una fotografia: dopo una modifica va rigenerata. La futura
orchestrazione dovrà ricaricare i file e ricontrollarne impronte e permessi prima di usarli.

```mermaid
flowchart LR
    F[File .SKILL] --> V[Validazione del contratto]
    V --> A[Agente di catalogazione]
    A --> C[Descrizioni AI con provenienza]
    T[Registro dei tool] --> E[Catalogo di selezione JSON]
    V --> E
    C --> E
    E -.-> O[Orchestrazione futura]
```

Questa fase introduce gestione, catalogazione e strumenti di lettura controllati.
Le pipeline investigative esistenti continuano a funzionare attraverso i loro servizi:
abilitare una skill nel registro non cambia automaticamente la catalogazione dei documenti,
la costruzione del grafo o le risposte della chat.


## Cataloghi dei documenti e reindicizzazione singola

Nella scheda **Evidence**, ogni riga offre **Apri catalogo** e **Reindicizza**.
**Apri catalogo** consulta le schede già salvate: la sezione **Riepilogo** mostra la sintesi
complessiva, **Pagine** permette di scorrere e filtrare classificazioni, entità, citazioni,
date e riferimenti, mentre **Provenienza** riporta modello, dizionario e data del catalogo.
Con `Invio` sulla pagina selezionata passi al dettaglio, con `/` al filtro e con `Esc`
torni ai documenti. Se non esiste un catalogo, la schermata lo indica e offre **Genera
catalogo**. L'elaborazione avviene in background, mostra l'avanzamento pagina per pagina e può
essere annullata; le pagine già completate restano salvate. Quando un catalogo esiste, lo stesso
comando diventa **Rigenera catalogo** e crea una nuova generazione senza confonderla con la
precedente. La sola consultazione e il comando **Aggiorna** non effettuano chiamate al modello.

**Reindicizza** ricostruisce l'indice RAG del solo documento scelto, anche quando risulta già
indicizzato. Gli altri documenti, i loro vettori e i loro stati restano invariati. Durante
l'elaborazione puoi usare **Cancel RAG**; una richiesta AI già inviata termina alla risposta
o al timeout, quindi l'annullamento impedisce i passi successivi. La rilevazione della lingua
usa al massimo 512 token e 60 secondi; ogni traduzione usa al massimo 8192 token e 120 secondi,
con ragionamento basso. I limiti inferiori configurati nel nodo mantengono la precedenza.

> **Catalogo e RAG hanno scopi diversi.** Il catalogo descrive il contenuto delle pagine;
> l'indice RAG serve a recuperare passaggi pertinenti alle domande. Reindicizzare aggiorna
> la ricerca e conserva il catalogo esistente. Il pulsante generale **Index RAG** continua
> invece a sincronizzare tutti i documenti dell'indagine.

## Provenienza e identità nel grafo

La generazione del grafo conserva la numerazione originale delle pagine PDF, comprese le pagine
vuote. L'analisi lavora per pagina, con segmenti sovrapposti per quelle lunghe; traduzioni o sintesi sono accompagnate
dal testo originale da cui prelevare le citazioni. Nei formati senza paginazione stabile il testo
è rappresentato come un'unica unità, senza attribuire numeri di pagina fisici.

Selezionando un nodo o un arco, il dettaglio mostra documento, pagina, citazione e risultato del
controllo sul testo originale. Una citazione inesistente, ambigua o attribuita alla pagina sbagliata
resta non verificata; le lacune compaiono anche negli avvisi dell'elaborazione. I grafi precedenti
rimangono leggibili, ma richiedono una nuova analisi per ottenere citazioni puntuali.

> **Citazione verificata e fatto verificato sono distinti.** Il controllo conferma la presenza
> del brano nella fonte, ammettendo differenze negli spazi. Non dimostra che l'affermazione sia vera
> o che la relazione la interpreti correttamente: i risultati dell'agente restano proposte.

Un nome o alias uguale non causa più una fusione automatica. Raven unisce identificatori forti
compatibili e univoci; conserva invece separati gli omonimi senza prove sufficienti e segnala
gli identificatori incompatibili. Queste note sono visibili nei dettagli. Un identificatore
discordante richiede un riesame, anche quando potrebbe dipendere da un rinnovo o da un errore
della fonte. Le pagine con soli nomi possono quindi produrre più candidati da verificare.

La sostituzione della proiezione Neo4j avviene in un'unica transazione: se una scrittura fallisce,
il precedente grafo Neo4j resta disponibile. Il salvataggio MongoDB e quello Neo4j sono operazioni
distinte; un problema di sincronizzazione Neo4j viene segnalato nell'esito dell'analisi.

## Cataloghi, affermazioni e aggiornamenti del grafo

In **Graph**, avvia **Nuova variante**, scegli il metodo e quindi apri **Affermazioni / copertura**. La scheda
**Affermazioni** permette di cercare un soggetto, una citazione o una fonte. Selezionando una
riga trovi la proposizione, la sua eventuale negazione, l'attribuzione e i confronti con altre
fonti. **Copertura** mostra ogni pagina, l'esito dell'analisi, lo stato del catalogo e gli errori;
da qui puoi aprire il catalogo del documento. `Invio` porta al dettaglio, `/` al filtro ed `Esc`
torna al grafo. I grafi precedenti rimangono consultabili e richiedono una nuova analisi per
popolare queste informazioni.

Durante la generazione compare una piccola rete animata con il tempo trascorso. La fase e il
conteggio dei documenti rimangono visibili accanto ai controlli; nei terminali piccoli
l'animazione occupa una sola riga. Il movimento indica attività, mentre l'avanzamento è quello
comunicato dall'elaborazione. L'animazione si arresta alla conclusione, all'errore o
all'annullamento e lascia disponibile il grafo precedente durante il lavoro.

Il catalogo suggerisce candidati e priorità, dopo il controllo di indagine, documento, lingua,
dizionario e impronta del testo della pagina. Non esclude pagine: anche quelle senza scheda,
con catalogo obsoleto o catalogazione fallita vengono lette. Le sintesi dei cataloghi non
diventano prove e non vengono usate come testo da citare.

> **Tempo del fatto e tempo dell'affermazione.** Una fonte pubblicata il 4 marzo può descrivere
> una collaborazione dal 21 febbraio al 2 marzo. Raven conserva separatamente il periodo a cui
> si riferisce il fatto e la data in cui la fonte lo afferma. Una cessazione successiva non
> annulla automaticamente la collaborazione passata. Date prive di giorno o mese mantengono
> la precisione originaria; le date sconosciute rimangono tali.

Le affermazioni conservano polarità, modalità dichiarativa o dubitativa, attribuzione e
qualificatori come importo, valuta o riferimento a un evento. Una smentita viene salvata come
affermazione negativa e non genera una relazione positiva. Il confronto deterministico richiede citazioni
verificate, predicati canonici e qualificatori compatibili. **Verifica tra fonti** aggiunge una
revisione semantica delle coppie candidate con formulazioni diverse, conservandone motivazioni
e disaccordi. Un passaggio dedicato propone anche confronti fra descrizioni con nomi o predicati
diversi; gli estratti abbreviati servono soltanto a trovare candidati, mentre la verifica usa
le citazioni complete. Queste proposte non modificano l'identità delle entità. Raven segnala
accordo, opposizione o differenza temporale; quando gli estremi hanno soltanto nomi coincidenti,
il confronto resta candidato e richiede verifica dell'identità. Identificatori incompatibili
impediscono anche questo abbinamento.

> **Due documenti non equivalgono a due fonti indipendenti.** Possono ripetere la stessa notizia.
> Il confronto non decide quale affermazione sia vera, non trasforma la confidenza del modello
> in attendibilità della fonte e non considera automaticamente più corretta la fonte più recente.

Generando una nuova variante, Raven riutilizza le estrazioni riuscite della precedente
istantanea. La chiave comprende pagina, testo, dizionario, lingua, preparazione effettiva, modello,
profilo di generazione, versioni dei contratti e suggerimenti del catalogo effettivamente usati.
Pagine cambiate, parziali o fallite vengono rielaborate. Affermazioni documentali e Verifica tra
fonti condividono soltanto il passaggio documentale compatibile; la revisione tra fonti viene
sempre eseguita. Eventi e temporalità esegue anche il proprio passaggio dedicato. I tre metodi
richiedono un modello disponibile: la sua assenza produce un errore esplicito. Il percorso
legacy può conservare i soli osservabili, senza presentarli come analisi semantica completa.
La riconciliazione e i confronti vengono ricostruiti dalle estrazioni delle fonti presenti:
rimuovere un documento elimina i suoi contributi dalla nuova istantanea. La cache conserva
le estrazioni prima delle fusioni, evitando di trascinare decisioni basate su fonti rimosse.

Se tutto il tentativo fallisce, il grafo precedente resta disponibile. Il record del tentativo
conserva gli esiti e i codici diagnostici per pagina; l'errore dell'elaborazione riporta le prime
pagine coinvolte. Le pagine riuscite di un risultato parziale rimangono consultabili.

Questa fase non decide automaticamente rettifiche o ritrattazioni. Predicati o qualificatori
formulati diversamente possono richiedere un confronto manuale; i riferimenti che dipendono da
più pagine richiedono riesame delle fonti. L'esecuzione delle skill configurabili e le future
orchestrazioni restano distinte da questo flusso di analisi.

## Recupero combinato di pagine e grafo

La scheda **Chat** combina automaticamente Qdrant e Neo4j. Qdrant trova i passaggi pertinenti;
Neo4j individua entità, affermazioni e confronti collegati nella stessa indagine e nella stessa
versione del grafo. Raven ricostruisce il contenuto dall'istantanea autorevole salvata in
MongoDB e recupera anche le pagine delle smentite collegate. Il pannello di stato mostra la
strategia utilizzata, il numero di passaggi e affermazioni e gli eventuali limiti del recupero.

```mermaid
flowchart LR
    D[Domanda] --> Q[Qdrant: passaggi e pagine]
    Q --> N[Neo4j: affermazioni e confronti]
    N --> M[Istantanea corrente: contenuto e provenienza]
    M --> P[Fonti originali e gruppi di confronto completi]
    P --> R[Risposta con citazioni]
```

Le citazioni **[E1]** identificano i passaggi documentali e **[G1]** le fonti riportate dal grafo.
L'elenco delle fonti mostra nome del documento e pagina, quando disponibili. Il testo originale
è distinto dalla copia tradotta usata per la ricerca. I vecchi indici vengono aggiornati al
formato per pagina alla successiva sincronizzazione; i cataloghi restano consultabili.

> **Un confronto deve mantenere entrambe le fonti.** Se il gruppo non entra nel contesto,
> Raven lo omette interamente e impedisce che una sua sola metà rientri attraverso i passaggi
> vettoriali o le citazioni delle entità. Il budget considera anche domanda, istruzioni e
> cronologia; usa una stima in caratteri e riserva spazio alla risposta. Non equivale al
> conteggio esatto dei token del modello.

Se Neo4j è indisponibile o non allineato, Raven cerca nell'istantanea corrente e lo segnala.
Se Qdrant o gli embedding non sono disponibili, prova il contesto del grafo. Documenti rimossi,
risultati di altre indagini e indici con impronta obsoleta vengono esclusi. Una modalità
degradata può fornire meno fonti: l'assenza di un risultato non dimostra l'assenza del fatto.

Il [confronto riproducibile RX41](docs/research/retrieval-benchmark.md) misura il recupero su
un corpus sintetico con domande, riferimenti attesi, negazioni e documenti estranei.
Graphiti è stato eseguito in un ambiente isolato su affermazioni inserite manualmente;
la variante delle comunità usa estratti collegati alle fonti. Entrambe rimangono sperimentali
e non sono attivate nella chat. La [valutazione delle alternative](docs/research/graph-retrieval-options.md)
spiega risultati, licenze, limiti e condizioni per una prova successiva con modello e PDF.
