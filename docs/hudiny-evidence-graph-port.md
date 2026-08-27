# Hudiny Evidence-to-Graph port

## Source analysis

The Raven implementation was mapped from the local Hudiny Link Intelligence implementation,
especially its investigation workflow, Evidence graph guide, extraction pipeline, deterministic
observable extractor, word chunker, agent prompts, consolidation component, run lifecycle, MongoDB
artifacts, and Neo4j synchronization boundary.

The behavioral sequence retained in Raven is:

```text
Evidence files
  -> immutable Raven copy
  -> normalized text extraction
  -> deterministic observables
  -> language-aware preparation
       |-- operational compression (default)
       |-- full text + translation only when needed
       `-- translation + overlapping chunks
  -> entity extraction agent
  -> relationship extraction agent (bounded to extracted entities)
  -> incremental entity resolution
  -> cross-document consolidation
  -> persistent run + graph checkpoint in MongoDB
  -> active graph synchronization in Neo4j
  -> terminal-native directed graph view
```

## Agents

Direct model execution lives under `src/raven/agents`, outside Textual handlers. The port includes:

- predominant operational-language detection;
- lossless translation that preserves protected literals and Evidence structure;
- operational compression that removes noise but is explicitly not a summary;
- named-entity extraction constrained to an allowlisted vocabulary;
- relationship extraction constrained to exact extracted entity endpoints;
- entity resolution against bounded same-type candidates.

All structured agent output is parsed defensively. Markdown fences and reasoning prefixes are
removed, unsupported entity or relationship types are discarded, confidence is clamped to
`0.0..1.0`, and Evidence IDs are supplied by the application rather than trusted from model output.

## Named-entity dictionaries

Raven keeps a project-level copy of the eleven Hudiny OSINT vocabulary definitions under
`config/osint-vocabularies`, with a packaged fallback under `src/raven/resources/dictionaries`.
The catalog validates the Hudiny `1.0` schema, size and file
limits, unique codes, inheritance, semantic versions, text fields, and the resolved entity-type
limit. `GENERAL_OSINT` is the default analysis domain and resolves `CORE@2.0.0` plus
`GENERAL_OSINT@1.0.0`. Domains are not globally overlaid: resolution loads only the selected
domain and the parents explicitly declared by its `extends` list.

The investigation creation form lists every definition marked `selectable_domain`. The chosen
domain is persisted on the investigation, displayed in its analysis profile, and used for every
subsequent Evidence-to-Graph run. Existing records without this field safely fall back to
`GENERAL_OSINT`.

The active snapshot is included in the entity-extraction prompt. Both the base type and subtype
must match a declared vocabulary entry; unsupported model output is discarded. Every graph run
persists the dictionary domain, component versions and SHA-256 snapshot hash in MongoDB.

The dictionary folder is configurable from `Configuration > Dictionaries` or with
`RAVEN_DICTIONARY_ROOT`. Selecting another folder changes subsequent runs without modifying the
bundled defaults.

## Language and preparation

The investigation stores one default `analysis_language`. `Original` is the default and preserves
the language of every Evidence. A graph run freezes that value together with its preparation mode.

- `Compress Evidence`: Hudiny-compatible default; compression can also translate operational prose
  to the investigation language.
- `Full text`: uses original text, or detects and losslessly translates it when the investigation
  has a target language.
- `Translate + overlapping chunks`: applies the same language rule and then splits at 1,000 words
  with a 100-word overlap before per-chunk extraction and deterministic consolidation.

## Persistence and provenance

MongoDB stores durable run state, per-Evidence ingestion state, model name, selected language and
mode, counts, errors, timestamps, and the latest graph checkpoint. Every entity and relationship
stores its supporting Evidence IDs, rationale, confidence, and `PROPOSED` status.

The TUI renders the checkpoint with `netext 0.5` through its native Textual `GraphView`.
Raven adapts domain objects to a directed Sugiyama layout, aggregates parallel visual edges,
retains all relationship records for inspection, and exposes fit/zoom/pan, mouse and keyboard
selection, entity search, level-of-detail styling, and an Evidence-grounded details panel.

Neo4j stores the active projection using `Investigation`, `Entity`, `CONTAINS`, and
`EVIDENCE_RELATION`. The domain relationship type remains a property so arbitrary model output is
never interpolated into Cypher. Previous projections are retained but marked inactive.

The MongoDB checkpoint remains displayable if Neo4j synchronization fails; the run becomes
`COMPLETED_WITH_WARNINGS` rather than losing the extracted result.

## Trust boundary

The graph view is an analytical proposal, not automatic verification. A model cannot create a
relationship whose endpoints were not extracted from the same bounded Evidence segment. Every
displayed item remains traceable to one or more Evidence document IDs. Qdrant is a rebuildable
semantic index and is not treated as factual graph storage.
