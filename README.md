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

## Evidence-to-Graph analysis

The opened investigation workspace includes a `Graph` tab. `Analyze Evidence` runs a persistent,
Evidence-grounded pipeline derived from Hudiny's Link Intelligence flow:

1. extract and normalize text from PDF, DOC/DOCX, or Markdown;
2. extract deterministic observables such as email addresses, URLs, domains, IPs, and hashes;
3. prepare the text with one of three strategies: operational compression (default), full text,
   or lossless translation followed by overlapping word chunks;
4. resolve only the investigation's selected Hudiny-compatible dictionary domain and its declared
   parents, then run dictionary-bounded entity extraction, relationship extraction, and
   incremental entity resolution on the shared AI node;
5. consolidate duplicates while retaining Evidence IDs, rationale, confidence, model, and run ID;
6. persist the run and latest graph snapshot in MongoDB and synchronize active nodes and edges to
   Neo4j;
7. render directed edges and isolated entities in a terminal-native graph view.

The graph view uses `netext`'s native Textual widget with a deterministic left-to-right
Sugiyama layout. It supports mouse selection, arrow-key panning, `J/K` entity navigation,
`+/-` zoom, `0`/`Fit` auto-fit, level-of-detail rendering for dense graphs, entity search,
directed relationship labels, and an Evidence/provenance detail panel. Multiple relationships
between the same pair are aggregated visually without discarding their underlying records.

If the AI node is unavailable, deterministic observables are still produced. Agent failures never
turn unsupported statements into verified facts: extracted graph items are stored as `PROPOSED`.
Every run freezes the investigation language, preparation mode, dictionary domain, component
versions, and dictionary snapshot hash for reproducibility. The eleven copied Hudiny dictionaries
live in `config/osint-vocabularies`; domains remain separate and are never globally overlaid.
The `Overview` tab can edit the case brief, questions, reference/normalization language, and
dictionary domain. Changing language or domain invalidates derived graph data and marks Evidence
for reprocessing; the source documents remain untouched. `GENERAL_OSINT` is used for legacy cases
and as the creation-form default. The same tab provides a confirmed investigation deletion flow
that removes Raven's Evidence directory, MongoDB records, chat history, Qdrant partition, and
Neo4j subgraph without modifying the original source files.
Qdrant remains the derived semantic-document index and is not used as the source of truth for graph
facts.

## Investigation chat and RAG

Every workspace has a `Chat` tab scoped to that investigation. On the first question, or with
`Index RAG`, Raven extracts the immutable Evidence copies, creates overlapping paragraph-aware
chunks, normalizes them into the investigation's reference language when one is selected, obtains
embeddings from the configured embedding model, and idempotently upserts them to Qdrant. A
mandatory `investigation_id` payload filter isolates retrieval between cases. Documents are
reindexed when either their SHA-256 or normalization language changes; deleted documents have
their vectors removed.

Each chat request receives:

- the most relevant Evidence chunks with stable `[E1]`, `[E2]`, … citation labels;
- the latest graph snapshot, including entity/relationship provenance, confidence, and status;
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

In **Configurazione → Skills & Tools** puoi scegliere la cartella dei file `.SKILL`.
Il valore viene applicato salvando la configurazione; `RAVEN_SKILL_ROOT`, quando presente,
ha la precedenza. La cartella predefinita è `skills` nella directory dati di Raven.
Cambiare cartella non sposta i file già presenti. **Gestisci** apre il registro che usa
la configurazione salvata: le modifiche ancora nel modulo non vengono applicate al registro.

La schermata **Capacità** separa le skill dai tool. Una skill è una definizione di lavoro
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
