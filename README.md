# Raven OSINT

Raven is a keyboard-first Python TUI for creating transparent, LLM-assisted OSINT
knowledge graphs. The current foundation provides a responsive home screen, infrastructure
bootstrap, connection monitoring, investigation creation, isolated evidence knowledge bases,
and non-secret endpoint configuration.

## Workspace appearance and review

Each newly uploaded document starts a background page-catalog job. A dedicated classification
agent reads every PDF page against the investigation's selected OSINT dictionary; unpaginated
Word and Markdown documents use explicitly labeled text sections. The agent proposes a title,
summary, category, topics, typed entities, dates, places, cross-references and investigative uses.
Source quotations and entity codes are validated before saving. A second agent creates the
document overview with page references. Classification and model confidence remain proposals,
including when source quotations match. Failed or empty pages remain visible as **Not classified**,
with an error reason; they never contribute `EVIDENCE_ONLY` to category counts. That category is
reserved for successfully analyzed passages outside the domain. The overview separates processed
pages, failed analyses and classifications needing review.

The page agent receives an explicit `code` for every dictionary entry. A response encoded as
`TYPE|SUBTYPE` is normalized only when that exact pair exists in the selected dictionary; unknown
codes, incompatible type/subtype pairs and entity names missing from the page still fail validation.
Requests include a JSON schema with the selected dictionary codes and the permitted categories
and uses. The model selects up to eight source-span IDs for citations; Raven stores the corresponding
original text, avoiding translated or rewritten quotations. Source support is still validated locally.

Catalog requests use low reasoning effort, a 4,096-token output cap and a 180-second request
timeout (or the configured timeout when shorter). Document summaries use 2,048 tokens and
120 seconds. These per-request limits do not change the global AI configuration. Provider errors,
timeouts and output-limit failures are saved and stop the catalog run without an immediate retry;
only a response that fails schema/source validation receives one additional attempt, with the
validation reason supplied as feedback. A document with invalid pages does not prevent the remaining
documents from being cataloged; the final job reports the incomplete documents and retains valid pages.
Confidence
measures support for the extraction, separately from the truth of the source's claims, including
fictional scenarios and denials. Bare page counters such as `2 / 8` are not cross-references.

Select a document in **Evidence** to see its catalog progress and overview. Press **Enter** for
the page catalog, searchable cards, full document overview and original text. **Catalog pages**
also processes existing documents and resumes interrupted work; **Cancel** stops after the
active model request. The **Jobs** screen includes catalog jobs. Run local OCR for scanned PDFs
with no extractable text, then update the catalog. Text/vector indexing remains independent;
uploads also queue RAG indexing when an embedding model is configured. Chat supplements vector
search with catalog-selected original passages, checking their page hashes before citing them.
Graph extraction retains its full-source scan.

RAG language detection is bounded to 60 seconds and translation to 120 seconds per chunk, with low
reasoning effort and finite output limits. Translation progress identifies the current chunk. Adding
another file remains available during RAG indexing; any wait for active analysis is cancellable.

Catalogs and individual pages persist separately in MongoDB. Re-running reuses successful pages;
changing the source profile, OCR cache, dictionary, language, model or catalog rules marks it stale.
The dictionary folder comes from Configuration and the domain from the investigation settings.
Dictionary JSON may optionally add `page_categories` and `page_uses` as arrays of uppercase codes;
these inherit through `extends` and supplement the general OSINT categories and uses. The
Corporate ownership dictionary includes ownership, governance and agreement page categories.

Raven uses one fixed appearance throughout the application; there are no selectable themes,
palettes or light/dark controls. Legacy color preferences are ignored when loading configuration.
Configuration → Interface offers language and comfortable or compact density settings.
Colors have fixed meanings: green for connected services, amber for checks or required setup,
and red for unavailable services. Status cards also show an explicit label and symbol.
Small terminals select the compact layout automatically.
The graph table keeps search visible at 80×24; press Enter on a row to open the full inspector,
review an entity or relationship, and open a supporting document. Filters combine review status,
source document, entity/relationship selection and minimum model confidence. Confidence is a
model estimate, not an independently measured probability.

Graph and RAG progress reaches the workspace through application events. Jobs includes case
names and retains completed, cancelled and failed runs. MongoDB writes for job history run in
an ordered background writer. Case changes invalidate active work and wait for it to leave its
publication section. Cancellation is cooperative: a provider call already in flight may finish
before the cancellation is observed. Once a graph checkpoint commits, the completed result is
retained even if a cancellation arrives afterward.

Each chat citation has a stable label, document, page or chunk, and the retrieved passage;
passages can be expanded in the conversation. Agent outputs must contain the expected JSON
collections. Conflicting identity identifiers block linking, and explicitly negated or uncertain
relationships are excluded. Supplied graph quotations are compared with original pages; missing
or unmatched quotations remain flagged for analyst review. A matching quotation verifies its
presence in the source, not the truth or interpretation of the claim.

MongoDB checkpoints are authoritative. Each checkpoint records whether its Neo4j projection
is pending; refreshing connected services retries the latest pending graph. Neo4j snapshot
updates run in one transaction. Analyst review reloads the latest checkpoint and preserves
the local decision history. This coordination applies to one Raven process; it does not provide
a distributed transaction across MongoDB, Neo4j, Qdrant and the filesystem.

RAG fingerprints include the embedding profile, chunking, normalization language and OCR cache.
Incomplete chunk manifests trigger reindexing. Evidence records retain their original storage
root, so changing the default folder affects subsequent imports. Legacy records are anchored in
MongoDB before a folder change. OCR caches record language and version and are replaced atomically.

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
  `relationships`, `graph_checkpoints`, `graph_analysis_runs`, `chat_messages`, `background_jobs`, and
  `app_metadata` collections plus their base indexes;
- Qdrant collection `raven_documents`, using cosine distance and 1024-dimensional vectors;
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
and independent Evidence, RAG, and Graph states. `Enter` opens the page-aware document Inspector;
`D` invokes deletion with explicit confirmation. PDF and Word page metadata are used when
available; estimated counts are prefixed with `~`, while unavailable legacy metadata is shown as
`N/D`.

Raven copies each document into `<configured-root>/<investigation-id>/`. The root is configured in
`Configuration > Storage` (or with `RAVEN_EVIDENCE_ROOT`), and the investigation workspace always
shows the effective destination. Raven creates the investigation subfolder when the case is
created. Changing the configured root does not move copies already stored under another root.
Original filenames, media types, formats, sizes, SHA-256 hashes, page metadata, storage keys, and
independent processing states are registered in MongoDB's `evidence_documents` collection. The
Inspector preserves PDF page boundaries, emits copyable page citation labels, and can run optional
local PDF OCR through Poppler/Tesseract; OCR output is cached under the investigation folder.
Deleting
evidence removes the Raven-managed copy and metadata but never modifies the original source file.

## Evidence-to-Graph analysis

The opened investigation workspace includes a `Graph` tab. `Analyze Evidence` runs a persistent,
Evidence-grounded pipeline derived from Hudiny's Link Intelligence flow:

1. extract and normalize text from PDF, DOC/DOCX, or Markdown;
2. prepare the text with Hudiny-compatible independent compression and overlapping-chunk flags;
   translation into the investigation language is automatic, and compression plus chunking may
   be enabled together;
3. resolve only the investigation's selected Hudiny-compatible dictionary domain and its declared
   parents, then run dictionary-bounded entity extraction, relationship extraction, and
   incremental entity resolution on the shared AI node;
4. consolidate duplicates while retaining Evidence IDs, rationale, confidence, model, and run ID;
5. persist the run and latest graph snapshot in MongoDB and synchronize active nodes and edges to
   Neo4j;
6. present every entity and relationship in a terminal-native table and generate a browser-grade
   interactive graph.

The default graph view is a `DataTable` browser that remains readable for disconnected and dense
graphs, supports entity-first search, and drives the Evidence/provenance inspector and review
controls. `Terminal map` retains the compact `netext` view as an optional convenience. `Open
interactive` writes and opens a Cytoscape.js explorer with pan/zoom, search, type/status filters,
CoSE, hierarchy, concentric, circle and grid layouts, plus a selection inspector. Its HTML contains
a relationship-table fallback if the interactive library cannot be loaded.

Analysts can explicitly mark every node or relationship `PROPOSED`, `VERIFIED`, or `REJECTED`;
reviews are persisted in MongoDB and synchronized to Neo4j. `Runs / Export` retains every graph
execution, restores a selected snapshot, and exports JSON, GraphML, entity CSV, relationship CSV,
and interactive HTML files under the case `exports` folder. Timeline and Map tabs derive temporal
and coordinate views from normalized graph identifiers without inventing missing dates or
locations.

Regex extraction is not merged into the graph: entities and relationships are created only from
validated model output. In particular, dotted section and paragraph numbers are left to contextual
LLM interpretation rather than being classified syntactically as IP addresses. If the AI node is
unavailable, the run fails explicitly. Agent failures never turn unsupported statements into
verified facts: extracted graph items are stored as `PROPOSED`.
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

## Persistent jobs and interface language

RAG indexing and graph analysis run in application-owned FIFO queues, independent from mounted
screens. Their queued/running/completed/failed/cancelled snapshots are persisted to MongoDB and
remain visible from the top-level `Jobs` workspace after navigating to another investigation.
The monitor shows pipeline type, investigation, stage, progress, update time, diagnostic message,
and supports cancellation of active work.

`Configuration > Interface` selects English or Italian UI chrome and persists the choice in the
public configuration. `RAVEN_UI_LANGUAGE=en|it` can override it for non-interactive launches.

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
- `RAVEN_UI_LANGUAGE`

`RAVEN_NEO4J_PASSWORD` takes precedence over the password stored by the TUI in the operating
system credential vault. This provides a non-interactive option for servers and containers where
a desktop keychain is unavailable.

## Navigation

The top menu exposes `Home`, `Investigations`, `Jobs`, and `Configuration`. `Investigations` opens the
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
