# Pipeline A -> LangGraph4j Integration Plan

**Date:** 2026-07-01  
**Scope:** Port Pipeline A, the organization document ingestion, analysis, structured extraction, chunking, embedding, and Qdrant indexing flow, from the current imperative `EdtPipelineADocumentIngestionService` orchestration to a LangGraph4j graph aligned with the Pipeline B graph implementation already present in the codebase.  
**Primary goal:** preserve current Pipeline A behavior first, then enable resumability, clearer stage observability, and selective parallelization where it is safe.

---

## 1. Development Guidelines Reviewed

Before planning this task, the `dev-guides` folder was reviewed as required by the project instructions. The implementation must follow these constraints:

- Backend components must live under `com.velia.components` and services under `com.velia.services`.
- Agent classes must remain under `com.velia.agents`; the graph should wrap existing agents through Pipeline A client interfaces where possible.
- DTOs exposed through API or persistence must use Lombok/Jackson/Swagger conventions and `@JsonIgnoreProperties(ignoreUnknown = true)` where resilient deserialization matters.
- New graph failures must use specific EDT exceptions, not generic `RuntimeException`.
- Logs and audit/event metadata must not include full document text, structured extraction payloads, prompts, secrets, or raw sensitive content.
- Existing MQTT document pipeline events and processing status transitions must remain deterministic.
- New mutating or document-processing flows must evaluate user activity audit impact before implementation.

---

## 2. Current Pipeline A - As-Is Analysis

### 2.1 Entry Point and Trigger

Pipeline A is triggered by `EdtRequestType.DOCUMENT_INGESTION` messages consumed by `EdtRequestFacadeProcessor`.

Current dispatch path:

```
EdtRequestFacadeProcessor.dispatchMessage(...)
  `-- if requestType == DOCUMENT_INGESTION
       `-- EdtPipelineADocumentIngestionService.execute(EdtDocumentProcessingRequestDto)
```

Pipeline B already has a feature-flagged graph path:

```
enterprise-digital-twin.pipeline-b.graph-enabled=true
EdtRequestFacadeProcessor
  `-- EdtPipelineBGraphService
       `-- EdtPipelineBGraphFactory
            `-- LangGraph4j StateGraph + MongoCheckpointSaver
```

Pipeline A should follow the same migration style: legacy path preserved, graph path enabled by a dedicated feature flag.

### 2.2 Current Sequential Flow

`EdtPipelineADocumentIngestionService.execute(...)` currently performs the full document pipeline in one imperative method:

```
A0 validate request
  `-- mark document PROCESSING / indexing PENDING
  `-- publish indexing stage update
A1 parse document routing metadata
  `-- DocumentParsingAgent.parse(...)
A2 extract raw text and normalize it
  |-- DocumentRawTextExtractionComponent.extractRawText(...)
  `-- ParsingNormalizationAgent.normalize(...)
A3 classify document type
  `-- DocumentTypeClassifierClient.classify(...)
A4 run structured extraction and persist payload
  |-- StructuredExtractionAgentClient.extract(...)
  `-- EdtExtractionPersistenceComponent.saveExtractionJson(...)
A5 chunk normalized text
  `-- ChunkingClient.chunk(...)
A6 compute embeddings
  `-- EmbeddingClient.embed(...)
A7 upsert vector points into Qdrant
  `-- QdrantUpsertClient.upsert(...)
A8 commit indexed state
  |-- IndexingStateCommitClient.commitIndexedState(...)
  |-- mark document PROCESSED / indexing INDEXED
  `-- publish completed event
```

Failure path:

```
InterruptedException
  `-- restore interrupt flag
  `-- mark document FAILED / indexing FAILED
  `-- publish failed event
  `-- throw EdtPipelineExecutionException

Any other exception
  `-- mark document FAILED / indexing FAILED
  `-- publish failed event
  `-- throw EdtPipelineExecutionException
```

### 2.3 Existing Pipeline A Extension Points

Pipeline A already has useful ports/adapters that can become graph node dependencies without rewriting agents:

| Responsibility | Existing class/interface |
|---|---|
| Parse routing | `DocumentParsingAgent` |
| Raw text extraction | `DocumentRawTextExtractionComponent` |
| Normalize text | `ParsingNormalizationAgent` |
| Classify type | `DocumentTypeClassifierClient` + `DocumentTypeClassifierAgentClient` |
| Structured extraction | `StructuredExtractionAgentClient` |
| Persist extraction | `EdtExtractionPersistenceComponent` |
| Chunking | `ChunkingClient` + `ChunkingAgentClient` |
| Embeddings | `EmbeddingClient` + `EmbeddingAgentClient` |
| Qdrant upsert | `QdrantUpsertClient` + `QdrantUpsertAgentClient` |
| Commit state | `IndexingStateCommitClient` + `IndexingStateCommitComponent` |
| UI/MQTT events | `OrganizationDocumentPipelineEventPublisher` |

### 2.4 Current Limitations

| Limitation | Impact |
|---|---|
| One long imperative method owns all stages | Hard to resume, test per stage, or inspect graph state |
| No checkpoint between expensive LLM/vector steps | Retry after crash may repeat parsing, classification, extraction, embeddings, and Qdrant upsert |
| Stage state is persisted only through document status and MQTT events | No structured execution state comparable to Pipeline B checkpoints |
| Failure handling is centralized and coarse | Hard to know exactly which node failed without log correlation |
| Some existing components throw generic Java exceptions | Graph path should wrap these in EDT-specific pipeline exceptions |
| Metadata JSON is manually assembled as a string | New nodes should use `ObjectMapper` or a small DTO/helper to avoid fragile escaping |

---

## 3. Target Architecture

### 3.1 Phase 1 Graph - Sequential Parity

The first implementation should reproduce the legacy output exactly before adding parallelism:

```
START
  -> validateRequest
  -> markProcessing
  -> parseDocument
  -> normalizeText
  -> classifyDocument
  -> extractStructuredPayload
  -> persistExtraction
  -> chunkDocument
  -> embedChunks
  -> upsertQdrant
  -> commitIndexedState
  -> markCompleted
END
```

Error handling should be handled by `EdtPipelineAGraphService`, mirroring Pipeline B service behavior:

```
graph failure
  `-- cancel timeout/interrupted execution when needed
  `-- mark document FAILED / indexing FAILED
  `-- publish failed event
  `-- throw EdtPipelineAGraphException
```

### 3.2 Phase 2 Graph - Checkpointed Sequential Graph

Add Mongo checkpointing after Phase 1 parity is proven:

```
RunnableConfig.threadId = requestUuid
GraphInput.resume(initialInput) when checkpoint exists
MongoCheckpointSaver-like implementation keyed by requestUuid
```

Resume must avoid re-running completed LLM/vector work. The checkpointed state must include enough data to continue from the next safe node.

### 3.3 Phase 3 Graph - Safe Parallel Lanes

Only parallelize deterministic or independent work after checkpointed parity:

```
chunkDocument
  -> embedChunks
        `-- can internally process chunks with existing agent/client rules
  -> optional future metadata enrichment lanes
```

Do not parallelize nodes that mutate the same `OrganizationDocumentDto` or rely on a strict stage order until idempotency is explicitly designed.

---

## 4. Proposed Graph State - `EdtPipelineAState`

Package: `com.velia.dto.edt.pipelinea.graph`

The state must extend LangGraph4j `AgentState`, using the same schema/channel style as `EdtPipelineBState`.

```java
public class EdtPipelineAState extends AgentState {

    public static final Map<String, Channel<?>> SCHEMA = Map.ofEntries(
            Map.entry("requestDto", nullableBase()),
            Map.entry("requestUuid", Channels.base(() -> "")),
            Map.entry("organizationUuid", Channels.base(() -> "")),
            Map.entry("documentUuid", Channels.base(() -> "")),
            Map.entry("storagePath", Channels.base(() -> "")),
            Map.entry("qdrantCollection", Channels.base(() -> "")),
            Map.entry("correlationId", Channels.base(() -> "")),

            Map.entry("stage", Channels.base(() -> "A0_VALIDATE_REQUEST")),
            Map.entry("errorMessage", Channels.base(() -> "")),
            Map.entry("failedNode", Channels.base(() -> "")),

            Map.entry("parsingResult", nullableBase()),
            Map.entry("rawText", Channels.base(() -> "")),
            Map.entry("extraction", nullableBase()),
            Map.entry("metadataJson", Channels.base(() -> "{}")),
            Map.entry("classification", nullableBase()),
            Map.entry("structuredPayloadJson", Channels.base(() -> "{}")),
            Map.entry("extractionRef", Channels.base(() -> "")),
            Map.entry("chunks", Channels.base((Supplier<List<DocumentChunkDto>>) List::of)),
            Map.entry("embeddingRefs", Channels.base((Supplier<List<ChunkEmbeddingRefDto>>) List::of)),
            Map.entry("qdrantPointRefs", Channels.base((Supplier<List<QdrantPointRefDto>>) List::of)),
            Map.entry("processingState", nullableBase())
    );

    public EdtPipelineAState(Map<String, Object> initData) {
        super(initData);
    }

    // Typed accessors follow the EdtPipelineBState pattern.
}
```

State rules:

- `rawText`, normalized text inside `DocumentExtractionDto`, and `structuredPayloadJson` are sensitive and can be large. Keep them in graph state only as long as needed for execution and checkpointing; never log them.
- If checkpoint size becomes too large, Phase 2 should persist text/payload artifacts by reference and store only artifact refs in graph state.
- `chunks`, `embeddingRefs`, and `qdrantPointRefs` should use base channels for Phase 1 because each stage has a single writer.
- Appender channels should be introduced only when true parallel fan-out is implemented.

---

## 5. Proposed Node Definitions

All nodes should live under:

`com.velia.components.edt.pipelinea.graph.nodes`

Each node should be a Spring `@Component`, preferably `@Scope(ConfigurableBeanFactory.SCOPE_PROTOTYPE)` if following Pipeline B's current graph factory pattern with `ObjectProvider`.

Node method signature:

```java
Map<String, Object> execute(EdtPipelineAState state) throws Exception
```

### 5.1 `ValidateRequestNode`

Replaces `validateRequest(...)`.

Responsibilities:

- Validate `requestDto`, `requestUuid`, `organizationUuid`, `documentUuid`, `storagePath`, and `requestType`.
- Return normalized request identifiers into graph state.
- Throw `EdtRequestValidationException` on invalid input.

### 5.2 `MarkProcessingNode`

Replaces the initial persistence/event setup.

Responsibilities:

- Call `EdtExtractionPersistenceComponent.markProcessing(documentUuid)`.
- Publish `DOCUMENT_PIPELINE_STAGE_CHANGED` for `indexing / INDEXING_IN_PROGRESS / PROCESSING`.
- Return `stage = A1_PARSE_DOCUMENT`.

### 5.3 `ParseDocumentNode`

Wraps `DocumentParsingAgent.parse(...)`.

Responsibilities:

- Build `DocumentParsingRequestDto`.
- Store `DocumentParsingResultDto`.
- Log parser kind, rejected flag, routing confidence, extension, and MIME type only.
- Return `stage = A2_NORMALIZE_TEXT`.

### 5.4 `NormalizeTextNode`

Wraps raw text extraction and parsing normalization.

Responsibilities:

- Call `DocumentRawTextExtractionComponent.extractRawText(...)`.
- Call `ParsingNormalizationAgent.normalize(...)`.
- Build metadata JSON through a structured helper, not manual string concatenation.
- Store `rawText`, `DocumentExtractionDto`, and `metadataJson`.
- Return `stage = A3_CLASSIFY_DOCUMENT`.

### 5.5 `ClassifyDocumentNode`

Wraps `DocumentTypeClassifierClient`.

Responsibilities:

- Build `ClassificationRequestDto` using normalized text and metadata JSON.
- Store `ClassificationResultDto`.
- Log document type, confidence, and prompt version only.
- Return `stage = A4_STRUCTURED_EXTRACTION`.

### 5.6 `ExtractStructuredPayloadNode`

Wraps `StructuredExtractionAgentClient`.

Responsibilities:

- Route extraction by `classification.documentType`.
- Store the structured payload JSON.
- Do not persist yet; persistence stays isolated in the next node.
- Return `stage = A4_PERSIST_EXTRACTION`.

### 5.7 `PersistExtractionNode`

Wraps `EdtExtractionPersistenceComponent.saveExtractionJson(...)`.

Responsibilities:

- Validate JSON through the existing persistence component.
- Persist document type, domain mapping, MIME type, and structured payload.
- Store `extractionRef`.
- Publish extraction stage update: `extraction / EXTRACTION_IN_PROGRESS / PROCESSING`.
- Return `stage = A5_CHUNK_DOCUMENT`.

### 5.8 `ChunkDocumentNode`

Wraps `ChunkingClient`.

Responsibilities:

- Build `ChunkingRequestDto`.
- Store `List<DocumentChunkDto>`.
- Log chunk count, estimated max chunk size, estimated overlap, and extraction UUID only.
- Return `stage = A6_EMBED_CHUNKS`.

### 5.9 `EmbedChunksNode`

Wraps `EmbeddingClient`.

Responsibilities:

- Build `EmbeddingRequestDto`.
- Store `List<ChunkEmbeddingRefDto>`.
- Log embedding count, chunk-with-vector count, vector dimension, and model name only.
- Return `stage = A7_UPSERT_QDRANT`.

### 5.10 `UpsertQdrantNode`

Wraps `QdrantUpsertClient`.

Responsibilities:

- Resolve collection from request or `QdrantCollectionNamingUtils.fromOrganizationUuid(...)`.
- Build `QdrantUpsertRequestDto`.
- Store `List<QdrantPointRefDto>`.
- Log point count and collection only.
- Return `stage = A8_COMMIT_INDEXED_STATE`.

### 5.11 `CommitIndexedStateNode`

Wraps `IndexingStateCommitClient`.

Responsibilities:

- Call `commitIndexedState(requestDto, qdrantPointRefs)`.
- Store `DocumentProcessingStateDto`.
- Return `stage = A9_MARK_COMPLETED`.

### 5.12 `MarkCompletedNode`

Final success node.

Responsibilities:

- Call `EdtExtractionPersistenceComponent.markIndexed(documentUuid)`.
- Publish `DOCUMENT_PROCESSING_COMPLETED`.
- Return `stage = A_DONE`.

---

## 6. Proposed Graph Factory

Package: `com.velia.components.edt.pipelinea.graph`

Class: `EdtPipelineAGraphFactory`

Use the same implementation style as `EdtPipelineBGraphFactory`:

- Build `StateGraph<EdtPipelineAState>` with `new EdtPipelineAStateSerializer()` if checkpointing needs JSON-safe state serialization.
- Resolve prototype nodes with `ObjectProvider`.
- Use `node_async(...)` for sequential Phase 1 nodes.
- Add `build()` and `build(BaseCheckpointSaver checkpointSaver)` overloads.

Graph edges:

```java
START -> validateRequest
validateRequest -> markProcessing
markProcessing -> parseDocument
parseDocument -> normalizeText
normalizeText -> classifyDocument
classifyDocument -> extractStructuredPayload
extractStructuredPayload -> persistExtraction
persistExtraction -> chunkDocument
chunkDocument -> embedChunks
embedChunks -> upsertQdrant
upsertQdrant -> commitIndexedState
commitIndexedState -> markCompleted
markCompleted -> END
```

---

## 7. Proposed Graph Service

Package: `com.velia.services.edt`

Class: `EdtPipelineAGraphService`

Responsibilities:

- Build initial input from `EdtDocumentProcessingRequestDto`.
- Use a feature-specific graph timeout property.
- Execute graph through `CompletableFuture` as Pipeline B does.
- Use `RunnableConfig.threadId(requestUuid)` for checkpoint/resume.
- On timeout, interruption, graph build failure, or execution failure:
  - cancel execution where possible;
  - mark document failed;
  - publish failed event;
  - throw `EdtPipelineAGraphException`.

Proposed properties:

```properties
enterprise-digital-twin.pipeline-a.graph-enabled=false
enterprise-digital-twin.pipeline-a.graph-timeout-seconds=600
enterprise-digital-twin.pipeline-a.graph-checkpoint-enabled=false
```

`EdtRequestFacadeProcessor` dispatch should become:

```java
if (pipelineAGraphEnabled) {
    edtPipelineAGraphService.execute(request);
} else {
    edtPipelineADocumentIngestionService.execute(request);
}
```

Keep the legacy service until graph parity, checkpointing, and rollout are complete.

---

## 8. Checkpointing Plan

Pipeline B already has:

- `MongoCheckpointSaver`
- `EdtPipelineBCheckpointDocument`
- `EdtPipelineBCheckpointEntryDto`
- `EdtPipelineBStateSerializer`
- `EdtPipelineBCheckpointRepository`

For Pipeline A, prefer a parallel package and collection to avoid mixing states:

```
com.velia.components.edt.pipelinea.graph.checkpoint
  `-- MongoPipelineACheckpointSaver.java

com.velia.dto.edt.pipelinea.graph
  |-- EdtPipelineACheckpointDocument.java
  |-- EdtPipelineACheckpointEntryDto.java
  `-- EdtPipelineAStateSerializer.java

com.velia.repositories
  `-- EdtPipelineACheckpointRepository.java
```

Open checkpoint design decision:

- **Option A - full state checkpoint:** fastest to implement, but can store large normalized text and structured payloads in checkpoint documents.
- **Option B - artifact-reference checkpoint:** safer for size and sensitive content, but requires text/payload artifact persistence before checkpointing.

Recommended sequence:

1. Phase 1: graph without checkpointing.
2. Phase 2a: full state checkpoint behind a disabled-by-default flag in non-production.
3. Phase 2b: replace large text/payload fields with artifact refs before production checkpoint rollout.

---

## 9. Exception Contract

Add dedicated exceptions:

```
com.velia.exceptions.edt.EdtPipelineAGraphException
com.velia.exceptions.edt.EdtPipelineANodeExecutionException
```

Rules:

- Validation failures continue to use `EdtRequestValidationException`.
- Graph orchestration failures use `EdtPipelineAGraphException`.
- Node wrappers should convert generic lower-level exceptions only when useful context is added.
- Interrupted failures must restore the interrupt flag.
- Failure messages persisted to `OrganizationDocumentDto.lastError` should be concise and must not include document text, payload JSON, prompts, or secrets.

---

## 10. Idempotency and Resume Rules

Before enabling checkpoint resume, define safe behavior per node:

| Node | Resume/idempotency requirement |
|---|---|
| `MarkProcessingNode` | Safe to repeat; clears prior error and returns to processing |
| `ParseDocumentNode` | Safe to repeat if no persisted side effect |
| `NormalizeTextNode` | Safe to repeat if no persisted side effect |
| `ClassifyDocumentNode` | Expensive LLM call; avoid repeat after checkpoint |
| `ExtractStructuredPayloadNode` | Expensive LLM call; avoid repeat after checkpoint |
| `PersistExtractionNode` | Repeating currently creates a new `extractionRef`; decide whether to persist extraction ref into `OrganizationDocumentDto.extractionRef` or make the node idempotent by request/document |
| `ChunkDocumentNode` | Safe to repeat if deterministic, but may be expensive |
| `EmbedChunksNode` | Expensive vector work; avoid repeat after checkpoint |
| `UpsertQdrantNode` | Must define idempotent point IDs or cleanup/overwrite policy before resume is enabled |
| `CommitIndexedStateNode` | Safe only if point refs are stable |
| `MarkCompletedNode` | Safe to repeat if document status and MQTT duplicate behavior are acceptable |

Important follow-up: `OrganizationDocumentDto` has an `extractionRef` field, but `EdtExtractionPersistenceComponent.saveExtractionJson(...)` currently returns an extraction ref without storing it in the document. The graph migration should decide whether this is intentional or should be fixed as part of idempotency.

---

## 11. Package Summary

```text
src/main/java/com/velia/components/edt/pipelinea/graph/
  EdtPipelineAGraphFactory.java

src/main/java/com/velia/components/edt/pipelinea/graph/nodes/
  ValidateRequestNode.java
  MarkProcessingNode.java
  ParseDocumentNode.java
  NormalizeTextNode.java
  ClassifyDocumentNode.java
  ExtractStructuredPayloadNode.java
  PersistExtractionNode.java
  ChunkDocumentNode.java
  EmbedChunksNode.java
  UpsertQdrantNode.java
  CommitIndexedStateNode.java
  MarkCompletedNode.java

src/main/java/com/velia/components/edt/pipelinea/graph/checkpoint/
  MongoPipelineACheckpointSaver.java

src/main/java/com/velia/services/edt/
  EdtPipelineAGraphService.java

src/main/java/com/velia/dto/edt/pipelinea/graph/
  EdtPipelineAState.java
  EdtPipelineAStateSerializer.java
  EdtPipelineACheckpointDocument.java
  EdtPipelineACheckpointEntryDto.java

src/main/java/com/velia/exceptions/edt/
  EdtPipelineAGraphException.java
  EdtPipelineANodeExecutionException.java

src/main/java/com/velia/repositories/
  EdtPipelineACheckpointRepository.java
```

---

## 12. Development Phases

Each phase is intentionally small and must be completed, verified, and explicitly confirmed before starting the next phase. Do not batch phases in one implementation PR unless the project owner has already approved combining them.

Phase transition rule:

1. Implement only the current phase scope.
2. Run the phase verification commands/tests.
3. Record the evidence in the PR or task comment.
4. Wait for explicit confirmation: "Phase N approved, continue to Phase N+1".
5. Start the next phase only after that confirmation.

### Phase 0 - Baseline Confirmation and Safety Net

Goal: freeze the expected legacy behavior before adding graph code.

Scope:

- Re-run and inspect the existing Pipeline A tests.
- Identify the exact legacy side effects that graph parity must preserve:
  - document processing/indexing status transitions;
  - structured extraction persistence fields;
  - Qdrant upsert request shape;
  - MQTT document events;
  - interruption/failure behavior.
- Add or update tests only if the current legacy behavior is not covered.
- No graph implementation in this phase.

Verification:

- `mvn test -Dtest=EdtPipelineADocumentIngestionServiceTest,QdrantUpsertAgentClientTest`
- If new baseline tests are added, run those targeted tests too.
- Confirm no production behavior changes except optional test-only additions.

Exit criteria:

- Legacy Pipeline A behavior is documented in test assertions.
- Any uncovered critical side effect has a failing-first or passing characterization test.
- The worktree diff contains no graph routing changes.

Confirmation checkpoint:

- Stop after Phase 0 and request approval to continue to Phase 1.

Phase 0 execution log:

- Status: completed on 2026-07-01.
- Activities performed:
  - Reviewed the existing legacy Pipeline A baseline tests.
  - Re-ran the Phase 0 baseline command.
  - Added characterization coverage for missing `storagePath` validation.
  - Added characterization coverage for the initial `markProcessing(...)` side effect.
  - Added characterization coverage for both document pipeline stage events:
    - `indexing / INDEXING_IN_PROGRESS / PROCESSING`;
    - `extraction / EXTRACTION_IN_PROGRESS / PROCESSING`.
  - Added characterization coverage for `saveExtractionJson(...)` arguments: request UUID, document UUID, document type, source MIME type, and structured payload.
  - Added characterization coverage for the Qdrant upsert request: request UUID, document UUID, resolved collection, chunks, and embedding refs.
  - Confirmed no graph routing or production graph implementation was introduced in this phase.
- Verification evidence:
  - Command: `mvn test -Dtest=EdtPipelineADocumentIngestionServiceTest,QdrantUpsertAgentClientTest`
  - Result: passed, 5 tests run, 0 failures, 0 errors, 0 skipped.
- Exit criteria result:
  - Legacy Pipeline A behavior is now more explicitly documented in test assertions.
  - Critical side effects for validation, status transitions, stage events, persistence, and Qdrant request shape are covered.
  - The worktree diff contains no graph routing changes.
- Next required action:
  - Wait for explicit approval before starting Phase 1.

### Phase 1 - Graph State, Exceptions, and Empty Skeleton

Goal: introduce the graph foundation without changing runtime behavior.

Scope:

- Add `EdtPipelineAState` with schema and typed accessors.
- Add `EdtPipelineAGraphException` and `EdtPipelineANodeExecutionException`.
- Add an `EdtPipelineAGraphFactory` skeleton that can compile a minimal graph in tests only.
- Add `EdtPipelineAStateTest`.
- Do not wire the graph into `EdtRequestFacadeProcessor`.
- Do not add graph service execution yet.

Verification:

- `mvn test -Dtest=EdtPipelineAStateTest`
- `mvn test -Dtest=EdtPipelineADocumentIngestionServiceTest`

Exit criteria:

- State defaults are deterministic.
- Base channels overwrite values correctly.
- Nullable fields behave like `EdtPipelineBState`.
- Existing Pipeline A tests still pass.

Confirmation checkpoint:

- Stop after Phase 1 and request approval to continue to Phase 2.

Phase 1 execution log:

- Status: completed on 2026-07-01.
- Activities performed:
  - Added `EdtPipelineAState` under `com.velia.dto.edt.pipelinea.graph`.
  - Added the Phase 1 graph schema with nullable object fields, base scalar fields, and base list fields for chunks, embedding refs, and Qdrant point refs.
  - Added typed accessors for request identifiers, stage/error fields, parsing/classification/extraction outputs, chunks, embedding refs, Qdrant point refs, and processing state.
  - Added `EdtPipelineAGraphException`.
  - Added `EdtPipelineANodeExecutionException`.
  - Added `EdtPipelineAGraphFactory` with a minimal `START -> noop -> END` skeleton graph.
  - Added `EdtPipelineAStateTest`.
  - Added `EdtPipelineAGraphFactoryTest` to prove the skeleton graph compiles and invokes.
  - Confirmed no facade routing, graph service, graph nodes, checkpointing, or runtime feature flag changes were introduced in this phase.
- Verification evidence:
  - Command: `mvn test -Dtest=EdtPipelineAStateTest,EdtPipelineAGraphFactoryTest,EdtPipelineADocumentIngestionServiceTest`
  - Result: passed, 9 tests run, 0 failures, 0 errors, 0 skipped.
- Exit criteria result:
  - State defaults are deterministic.
  - Base channels overwrite values correctly.
  - Nullable fields behave like `EdtPipelineBState`.
  - The minimal graph skeleton compiles and preserves input state values while updating only `stage`.
  - Existing Pipeline A tests still pass.
- Next required action:
  - Wait for explicit approval before starting Phase 2.

### Phase 2 - Sequential Nodes Without Facade Routing

Goal: implement node-level behavior while keeping the legacy service as the only active runtime path.

Scope:

- Add all Phase 1 sequential graph nodes:
  - `ValidateRequestNode`
  - `MarkProcessingNode`
  - `ParseDocumentNode`
  - `NormalizeTextNode`
  - `ClassifyDocumentNode`
  - `ExtractStructuredPayloadNode`
  - `PersistExtractionNode`
  - `ChunkDocumentNode`
  - `EmbedChunksNode`
  - `UpsertQdrantNode`
  - `CommitIndexedStateNode`
  - `MarkCompletedNode`
- Build the full sequential `EdtPipelineAGraphFactory`.
- Add node tests with mocked dependencies.
- Verify every node returns only keys declared in `EdtPipelineAState.SCHEMA`.
- Do not add `EdtPipelineAGraphService` yet.
- Do not route queue messages to the graph yet.

Verification:

- `mvn test -Dtest=EdtPipelineAStateTest,EdtPipelineAGraphFactoryTest`
- `mvn test -Dtest=*PipelineA*NodeTest`
- `mvn test -Dtest=EdtPipelineADocumentIngestionServiceTest`

Exit criteria:

- The graph compiles.
- Node execution order is deterministic.
- Node tests cover happy and local failure paths.
- No INFO/WARN/ERROR log includes raw document text, normalized text, structured payload JSON, prompts, or secrets.
- Legacy Pipeline A remains the only runtime path.

Confirmation checkpoint:

- Stop after Phase 2 and request approval to continue to Phase 3.

Phase 2 execution log:

- Status: completed on 2026-07-01.
- Activities performed:
  - Replaced the Phase 1 skeleton graph with the full sequential Pipeline A graph factory.
  - Added prototype-scoped graph nodes:
    - `ValidateRequestNode`
    - `MarkProcessingNode`
    - `ParseDocumentNode`
    - `NormalizeTextNode`
    - `ClassifyDocumentNode`
    - `ExtractStructuredPayloadNode`
    - `PersistExtractionNode`
    - `ChunkDocumentNode`
    - `EmbedChunksNode`
    - `UpsertQdrantNode`
    - `CommitIndexedStateNode`
    - `MarkCompletedNode`
  - Kept all nodes as thin wrappers around the existing Pipeline A agents/components/clients.
  - Kept the legacy `EdtPipelineADocumentIngestionService` as the only runtime path.
  - Confirmed no `EdtPipelineAGraphService`, facade routing, feature flag, or checkpointing was introduced in this phase.
  - Updated `EdtPipelineAGraphFactoryTest` to verify the sequential graph compiles and runs all mocked nodes in order.
  - Added `EdtPipelineAGraphNodesTest` covering all Phase 2 nodes with mocked dependencies.
  - Verified node outputs use only keys declared in `EdtPipelineAState.SCHEMA`.
  - Used structured JSON generation for parsing metadata in `NormalizeTextNode` instead of manual string concatenation.
- Verification evidence:
  - Command: `mvn test -Dtest=EdtPipelineAStateTest,EdtPipelineAGraphFactoryTest,EdtPipelineAGraphNodesTest,EdtPipelineADocumentIngestionServiceTest`
  - Result: passed, 22 tests run, 0 failures, 0 errors, 0 skipped.
- Exit criteria result:
  - The graph compiles.
  - Node execution order is deterministic in the factory test.
  - Node tests cover happy paths and local validation/failure path for request validation.
  - Node outputs are schema-bound.
  - Legacy Pipeline A tests still pass.
  - Legacy Pipeline A remains the only runtime path.
- Next required action:
  - Wait for explicit approval before starting Phase 3.

### Phase 3 - Graph Service Behind Disabled Feature Flag

Goal: make the graph executable through a service while keeping it disabled by default.

Scope:

- Add `EdtPipelineAGraphService`.
- Add configuration:
  - `enterprise-digital-twin.pipeline-a.graph-enabled=false`
  - `enterprise-digital-twin.pipeline-a.graph-timeout-seconds=600`
- Update `EdtRequestFacadeProcessor` to choose graph vs legacy only by feature flag.
- Keep the default value disabled.
- Add facade routing tests for enabled and disabled flags.
- Add graph service tests for happy path, timeout, interruption, and execution failure.

Verification:

- `mvn test -Dtest=EdtPipelineAGraphServiceTest`
- `mvn test -Dtest=EdtRequestFacadeProcessorGraphFlagTest`
- `mvn test -Dtest=EdtPipelineADocumentIngestionServiceTest`

Exit criteria:

- With graph flag disabled, `DOCUMENT_INGESTION` still calls `EdtPipelineADocumentIngestionService`.
- With graph flag enabled in test only, `DOCUMENT_INGESTION` calls `EdtPipelineAGraphService`.
- Graph failures mark document failed and publish failure events.
- Interrupted graph execution restores the interrupt flag.
- Default application configuration does not enable Pipeline A graph.

Confirmation checkpoint:

- Stop after Phase 3 and request approval to continue to Phase 4.

Phase 3 execution log:

- Status: completed on 2026-07-01.
- Activities performed:
  - Added `EdtPipelineAGraphService` under `com.velia.services.edt`.
  - Added `enterprise-digital-twin.pipeline-a.graph-enabled=false` to application configuration.
  - Added `enterprise-digital-twin.pipeline-a.graph-timeout-seconds=600` to application configuration.
  - Updated `EdtRequestFacadeProcessor` to route `DOCUMENT_INGESTION` requests to the graph service only when `pipeline-a.graph-enabled` is true.
  - Preserved legacy `EdtPipelineADocumentIngestionService` as the default Pipeline A runtime path.
  - Added `EdtPipelineAStateSerializer` because LangGraph4j clones graph state during normal invocation, and `EdtDocumentProcessingRequestDto` is not Java-serializable.
  - Updated `EdtPipelineAGraphFactory` to use the custom Pipeline A state serializer.
  - Added `EdtPipelineAGraphServiceTest` covering:
    - happy path;
    - graph execution failure;
    - graph timeout;
    - graph interruption with interrupt flag restored;
    - graph build failure.
  - Extended `EdtRequestFacadeProcessorGraphFlagTest` to cover Pipeline A graph flag enabled/disabled routing.
  - Confirmed no checkpoint repository, checkpoint saver, or resume behavior was introduced in this phase.
- Verification evidence:
  - Command: `mvn test -Dtest=EdtPipelineAGraphServiceTest,EdtRequestFacadeProcessorGraphFlagTest,EdtPipelineADocumentIngestionServiceTest`
  - Result: passed, 13 tests run, 0 failures, 0 errors, 0 skipped.
  - Additional regression command: `mvn test -Dtest=EdtPipelineAStateTest,EdtPipelineAGraphFactoryTest,EdtPipelineAGraphNodesTest,EdtPipelineAGraphServiceTest,EdtRequestFacadeProcessorGraphFlagTest,EdtPipelineADocumentIngestionServiceTest`
  - Additional regression result: passed, 31 tests run, 0 failures, 0 errors, 0 skipped.
- Exit criteria result:
  - With graph flag disabled, `DOCUMENT_INGESTION` still calls `EdtPipelineADocumentIngestionService`.
  - With graph flag enabled in tests only, `DOCUMENT_INGESTION` calls `EdtPipelineAGraphService`.
  - Graph failures mark the document failed and publish failure events.
  - Interrupted graph execution restores the interrupt flag.
  - Default application configuration does not enable Pipeline A graph.
  - Checkpointing remains out of scope.
- Phase 6 planning note:
  - The state serializer originally listed in Phase 6 now exists because it is required for non-checkpoint graph invocation. Phase 6 should reuse/extend it for checkpoint payload methods instead of adding it from scratch.
- Next required action:
  - Wait for explicit approval before starting Phase 4.

### Phase 4 - End-to-End Sequential Parity

Goal: prove the disabled-by-default graph path produces the same externally visible behavior as the legacy path.

Scope:

- Add integration-style parity tests with mocked agents/clients.
- Compare legacy service vs graph service for the same request and mocked outputs.
- Cover:
  - happy path;
  - classification failure;
  - structured extraction interruption;
  - Qdrant upsert failure;
  - no chunks or no embeddings where current behavior allows it.
- Keep checkpointing out of scope.
- Keep graph flag disabled by default.

Verification:

- `mvn test -Dtest=EdtPipelineAGraphParityTest`
- `mvn test -Dtest=EdtPipelineADocumentIngestionServiceTest,EdtPipelineAGraphServiceTest,EdtRequestFacadeProcessorGraphFlagTest`

Exit criteria:

- Final document status/indexing status match legacy behavior.
- Persisted document type/domain/source MIME/structured payload match legacy behavior.
- MQTT event calls match legacy behavior.
- Failure messages are equivalent or intentionally safer without losing operational meaning.
- No checkpoint or resume code has been introduced yet.

Confirmation checkpoint:

- Stop after Phase 4 and request approval to continue to Phase 5.

Phase 4 execution log:

- Status: completed on 2026-07-01.
- Activities performed:
  - Added `EdtPipelineAGraphParityTest`.
  - Built a legacy harness around `EdtPipelineADocumentIngestionService` with mocked Pipeline A dependencies.
  - Built a graph harness around `EdtPipelineAGraphService` and the real sequential `EdtPipelineAGraphFactory`, with mocked node dependencies.
  - Compared legacy and graph side effects for the same request and equivalent mocked outputs.
  - Covered happy path side effects:
    - `markProcessing(...)`;
    - indexing stage MQTT event;
    - structured extraction persistence arguments;
    - extraction stage MQTT event;
    - indexing state commit;
    - `markIndexed(...)`;
    - completed MQTT event;
    - no failed event.
  - Covered classification failure parity.
  - Covered structured extraction interruption parity, including interrupt flag restoration for both legacy and graph paths.
  - Covered Qdrant upsert failure parity.
  - Covered empty chunks/empty embeddings path parity.
  - Updated `EdtPipelineAGraphService` so root-cause `InterruptedException` from graph worker execution restores the caller interrupt flag, matching legacy behavior.
  - Kept checkpointing and resume behavior out of scope.
  - Kept Pipeline A graph disabled by default.
- Verification evidence:
  - Command: `mvn test -Dtest=EdtPipelineAGraphParityTest,EdtPipelineAGraphServiceTest,EdtRequestFacadeProcessorGraphFlagTest,EdtPipelineADocumentIngestionServiceTest`
  - Result: passed, 18 tests run, 0 failures, 0 errors, 0 skipped.
  - Additional regression command: `mvn test -Dtest=EdtPipelineAStateTest,EdtPipelineAGraphFactoryTest,EdtPipelineAGraphNodesTest,EdtPipelineAGraphServiceTest,EdtPipelineAGraphParityTest,EdtRequestFacadeProcessorGraphFlagTest,EdtPipelineADocumentIngestionServiceTest`
  - Additional regression result: passed, 36 tests run, 0 failures, 0 errors, 0 skipped.
- Exit criteria result:
  - Final success side effects match legacy behavior for the covered happy paths.
  - Failure side effects match legacy behavior for classification failure, structured extraction interruption, and Qdrant failure.
  - Empty chunk/embedding path remains successful in both paths.
  - Failure messages are root-cause messages, not graph wrapper messages.
  - No checkpoint or resume code has been introduced.
- Test log note:
  - Some test runs intentionally print LangGraph4j `ERROR` logs for forced failure scenarios; the Maven result is still successful and those logs are expected.
- Next required action:
  - Wait for explicit approval before starting Phase 5.

### Phase 5 - Checkpoint Design Decision Only

Goal: choose the checkpoint storage strategy before implementing persistence.

Scope:

- Decide between:
  - full graph state checkpoint;
  - artifact-reference checkpoint for raw/normalized text and structured payload;
  - hybrid checkpoint.
- Decide whether `EdtExtractionPersistenceComponent.saveExtractionJson(...)` must persist `OrganizationDocumentDto.extractionRef`.
- Decide Qdrant idempotency strategy before any resume-capable graph writes.
- Update this plan with the chosen decisions.
- No checkpoint code in this phase unless explicitly approved.

Completed activities:

- Reviewed the current Pipeline A persistence and indexing behavior that affects resume safety:
  - `EdtExtractionPersistenceComponent.saveExtractionJson(...)` generates and returns an extraction ref, but does not currently persist it into `OrganizationDocumentDto.extractionRef`.
  - `QdrantUpsertAgentClient` writes chunks through LangChain4j `EmbeddingStore.addAll(...)`, so Pipeline A does not currently control deterministic Qdrant point IDs on this path.
  - Qdrant chunk metadata already includes `documentUuid`.
  - `QdrantRuntimeService.deleteChunksByDocumentUuid(...)` already provides a document-level cleanup primitive that can be reused for idempotent re-indexing.
- Closed the Phase 5 checkpoint storage decision:
  - Use a hybrid artifact-reference checkpoint strategy.
  - Store small graph metadata, request identifiers, stage status, classification metadata, chunk references, embedding references, Qdrant point references, and persisted domain references in checkpoint documents.
  - Do not store large or sensitive raw text, normalized text, or structured payload JSON directly in production checkpoint payloads.
  - Store large intermediate artifacts by reference when resume requires them, using Pipeline A artifact documents keyed by request UUID, document UUID, stage, and artifact type.
  - Continue to persist the final structured extraction payload on `OrganizationDocumentDto` as the domain result, because that is already the existing business persistence model.
- Closed the extraction reference decision:
  - `EdtExtractionPersistenceComponent.saveExtractionJson(...)` should persist the generated or reused extraction ref into `OrganizationDocumentDto.extractionRef`.
  - Resume/idempotency work should prefer an existing extraction ref for the same document/request before generating a new one.
- Closed the Qdrant idempotency decision:
  - Use delete-then-upsert by `documentUuid` for the current Pipeline A graph path.
  - This matches the existing metadata shape and avoids a larger rewrite of the LangChain4j embedding-store based client.
  - Deterministic point IDs can remain a later hardening option if Pipeline A moves to a lower-level Qdrant client.
- Closed/deferred supporting design decisions:
  - Keep `StructuredExtractionAgentClient` as a concrete component for now; current graph tests already mock it successfully, so an interface extraction is not required for this migration.
  - Do not add dedicated `AgentRuntimeEventPublisher` events in Phase 6. Existing agent lifecycle events plus document MQTT events remain sufficient until a later observability phase.

Verification:

- Review updated decision notes in this Markdown file.
- Confirm the chosen strategy accounts for sensitive data, checkpoint size, and resume idempotency.
- Confirm affected DTO/repository changes are identified.

Exit criteria:

- Open decisions in section 15 are either closed or explicitly deferred with owner approval.
- The next phase has an agreed checkpoint implementation target.

Confirmation checkpoint:

- Stop after Phase 5 and request approval to continue to Phase 6.

### Phase 6 - Checkpoint Serialization and Resume

Goal: add checkpoint support after the storage/idempotency decisions are approved.

Scope:

- Reuse/extend `EdtPipelineAStateSerializer` for checkpoint payload serialization.
- Add Pipeline A checkpoint DTOs, repository, and saver.
- Add Pipeline A artifact DTOs, repository, and component for large resume artifacts such as raw text and normalized text.
- Store artifact references in checkpoint payloads instead of storing large text/payload fields directly.
- Add checkpoint-enabled graph factory overload.
- Add configuration:
  - `enterprise-digital-twin.pipeline-a.graph-checkpoint-enabled=false`
- Add resume tests from intermediate nodes.
- Keep checkpointing disabled by default.

Completed activities:

- Added Pipeline A checkpoint persistence:
  - `EdtPipelineACheckpointDocument`
  - `EdtPipelineACheckpointEntryDto`
  - `EdtPipelineACheckpointRepository`
  - `MongoPipelineACheckpointSaver`
- Added Pipeline A artifact persistence for large resume content:
  - `EdtPipelineAArtifactDocument`
  - `EdtPipelineAArtifactType`
  - `EdtPipelineAArtifactRepository`
  - `EdtPipelineAArtifactComponent`
- Extended `EdtPipelineAState` with artifact reference fields:
  - `rawTextArtifactRef`
  - `normalizedTextArtifactRef`
  - `structuredPayloadArtifactRef`
- Extended `EdtPipelineAStateSerializer` with checkpoint payload helpers:
  - normal in-memory graph cloning keeps full runtime state;
  - checkpoint serialization redacts `rawText`, `structuredPayloadJson`, and `DocumentExtractionDto.normalizedText`;
  - artifact refs and small metadata remain in the checkpoint payload.
- Updated graph nodes to persist large intermediates as artifacts:
  - `NormalizeTextNode` stores raw text and normalized text artifacts;
  - `ExtractStructuredPayloadNode` stores structured payload artifacts.
- Updated `MongoPipelineACheckpointSaver` to hydrate redacted checkpoint state from artifact refs before returning checkpoints to LangGraph4j.
- Added checkpoint-aware graph compilation through `EdtPipelineAGraphFactory.build(BaseCheckpointSaver)`.
- Added checkpoint-aware execution to `EdtPipelineAGraphService`:
  - checkpointing is controlled by `enterprise-digital-twin.pipeline-a.graph-checkpoint-enabled=false`;
  - default execution still uses the non-checkpoint graph path;
  - when enabled, the service detects existing checkpoints and invokes the graph with `GraphInput.resume(...)`.
- Updated Phase 4 parity harness to account for the new artifact dependency without changing legacy side-effect expectations.

Verification:

- `mvn test -Dtest=EdtPipelineAStateSerializerTest`
- `mvn test -Dtest=MongoPipelineACheckpointSaverTest`
- `mvn test -Dtest=EdtPipelineAGraphServiceResumeTest`
- Run Phase 4 parity tests again.

Executed verification:

- Passed: `mvn test -Dtest=EdtPipelineAStateSerializerTest,MongoPipelineACheckpointSaverTest,EdtPipelineAGraphServiceResumeTest`
  - Result: 4 tests passed.
- Initial regression found stale Phase 4 parity harness construction for `NormalizeTextNode` and `ExtractStructuredPayloadNode`.
  - Fixed by injecting a mocked `EdtPipelineAArtifactComponent` and stubbing artifact writes.
- Passed: `mvn test -Dtest=EdtPipelineAStateTest,EdtPipelineAStateSerializerTest,MongoPipelineACheckpointSaverTest,EdtPipelineAArtifactComponentTest,EdtPipelineAGraphFactoryTest,EdtPipelineAGraphNodesTest,EdtPipelineAGraphServiceTest,EdtPipelineAGraphServiceResumeTest,EdtPipelineAGraphParityTest,EdtRequestFacadeProcessorGraphFlagTest,EdtPipelineADocumentIngestionServiceTest`
  - Result: 42 tests passed.
  - Note: LangGraph4j error logs during forced failure/interruption/Qdrant-failure tests are expected and covered by assertions.

Exit criteria:

- Resume from a checkpoint does not re-run already completed expensive nodes in tests.
- Checkpoint records do not expose raw text, normalized text, or structured payload JSON directly in production payloads.
- Resume either reloads required large intermediates through artifact references or recomputes them from the original source when that is safer.
- Checkpoint disabled path behaves exactly like Phase 4.
- Legacy fallback remains available.

Confirmation checkpoint:

- Stop after Phase 6 and request approval to continue to Phase 7.

### Phase 7 - Idempotency Hardening

Goal: make repeated graph/resume executions safe around persisted extraction and Qdrant writes.

Scope:

- Implement the approved extraction ref behavior.
- Implement the approved Qdrant idempotency policy.
- Reuse existing extraction refs before generating new refs during repeated graph execution.
- Delete existing Qdrant points for the document UUID before graph-path upsert, then upsert the current chunk set.
- Add duplicate-resume tests around persistence, state commit, and Qdrant upsert.
- Validate duplicate MQTT behavior is either prevented or accepted by documented policy.

Completed activities:

- Updated `EdtExtractionPersistenceComponent.saveExtractionJson(...)` to make extraction persistence idempotent:
  - reuses an existing `OrganizationDocumentDto.extractionRef` when present;
  - generates a new extraction ref only when the document does not already have one;
  - persists the resolved extraction ref back into `OrganizationDocumentDto.extractionRef` together with document type, domain, source MIME type, and structured payload.
- Updated graph-path Qdrant upsert behavior:
  - `UpsertQdrantNode` now resolves the target collection once;
  - deletes existing Qdrant points for the current `documentUuid` before every graph-path upsert;
  - upserts the current chunk/embedding set after cleanup.
- Kept the legacy imperative Pipeline A service behavior unchanged except for the shared extraction-ref persistence improvement.
- Added `EdtPipelineAGraphIdempotencyTest` covering:
  - generated extraction ref persistence;
  - extraction ref reuse on repeated persistence for the same document;
  - delete-then-upsert ordering for repeated graph-path Qdrant writes.
- Updated graph node and parity tests for the new Qdrant cleanup dependency.
- Duplicate MQTT behavior remains accepted for this phase:
  - repeated graph execution may still emit the existing stage/completion events;
  - Phase 7 focuses on persisted domain state and Qdrant duplicate safety;
  - dedicated event deduplication is deferred unless Phase 8 observability/runbook work identifies it as required.

Verification:

- `mvn test -Dtest=EdtPipelineAGraphIdempotencyTest`
- `mvn test -Dtest=EdtPipelineAGraphServiceResumeTest`
- Run Phase 4 parity tests again.

Executed verification:

- Passed: `mvn test -Dtest=EdtPipelineAGraphIdempotencyTest`
  - Result: 2 tests passed.
- Passed: `mvn test -Dtest=EdtPipelineAGraphIdempotencyTest,EdtPipelineAGraphServiceResumeTest,EdtPipelineAGraphParityTest`
  - Result: 8 tests passed.
- Passed: `mvn test -Dtest=EdtPipelineAStateTest,EdtPipelineAStateSerializerTest,MongoPipelineACheckpointSaverTest,EdtPipelineAArtifactComponentTest,EdtPipelineAGraphFactoryTest,EdtPipelineAGraphNodesTest,EdtPipelineAGraphServiceTest,EdtPipelineAGraphServiceResumeTest,EdtPipelineAGraphIdempotencyTest,EdtPipelineAGraphParityTest,EdtRequestFacadeProcessorGraphFlagTest,EdtPipelineADocumentIngestionServiceTest,QdrantUpsertAgentClientTest`
  - Result: 45 tests passed.
  - Note: LangGraph4j error logs during forced failure/interruption/Qdrant-failure tests are expected and covered by assertions.

Exit criteria:

- Re-running the graph with the same `requestUuid` does not create inconsistent document metadata.
- Qdrant duplicate behavior is deterministic and covered by tests.
- Document status ends as `PROCESSED` / `INDEXED` from an externally visible perspective.

Confirmation checkpoint:

- Stop after Phase 7 and request approval to continue to Phase 8.

### Phase 8 - Observability and Operational Runbook

Goal: make graph execution diagnosable before any rollout.

Scope:

- Add node-level stage naming documentation.
- Add safe log markers for request UUID, organization UUID, document UUID, stage, and failed node.
- Add or update an operational runbook section for stuck/failed Pipeline A graph requests.
- Decide whether existing agent lifecycle events plus document MQTT events are sufficient, or whether graph service should emit additional runtime events.

Completed activities:

- Added node-level failure metadata:
  - `EdtPipelineANodeExecutionException` now carries `nodeId` and `stage`.
  - `EdtPipelineAGraphFactory` wraps each graph node with node/stage metadata before handing it to LangGraph4j.
  - `EdtPipelineAGraphService` emits a safe warning marker on graph failure with request UUID, organization UUID, document UUID, failure stage, and failed node.
- Kept failure log content safe:
  - logs include identifiers, stage, node, counts, document type, parser kind, status, and collection names;
  - logs do not include raw document text, normalized text, structured extraction JSON, chunk text, embedding vectors, or checkpoint payloads;
  - the service-level failure marker does not log the free-form exception message because agent/parser messages may contain sensitive details.
- Runtime event decision:
  - existing document MQTT events plus existing agent lifecycle/log events are sufficient for Phase 8 and Phase 9 controlled rollout;
  - no dedicated `AgentRuntimeEventPublisher` events are added in this phase;
  - revisit this decision only if controlled rollout shows operators cannot diagnose failures from logs, document status, checkpoint records, and existing events.

Node/stage map:

| Graph node | Stage marker | Purpose |
| --- | --- | --- |
| `validateRequest` | `A0_VALIDATE_REQUEST` | Validate required request identifiers and storage/Qdrant inputs. |
| `markProcessing` | `A0_MARK_PROCESSING` | Mark document processing/indexing as in progress and publish indexing start event. |
| `parseDocument` | `A1_PARSE_DOCUMENT` | Route and parse source file. |
| `normalizeText` | `A2_NORMALIZE_TEXT` | Extract raw text, normalize text, and persist large text artifacts. |
| `classifyDocument` | `A3_CLASSIFY_DOCUMENT` | Classify document type. |
| `extractStructuredPayload` | `A4_STRUCTURED_EXTRACTION` | Run structured extraction agent and persist structured payload artifact. |
| `persistExtraction` | `A4_PERSIST_EXTRACTION` | Persist structured extraction result and extraction ref. |
| `chunkDocument` | `A5_CHUNK_DOCUMENT` | Split normalized text into chunks. |
| `embedChunks` | `A6_EMBED_CHUNKS` | Generate embedding references. |
| `upsertQdrant` | `A7_UPSERT_QDRANT` | Delete existing document points and upsert current points. |
| `commitIndexedState` | `A8_COMMIT_INDEXED_STATE` | Persist final indexing state metadata. |
| `markCompleted` | `A9_MARK_COMPLETED` | Mark document as processed/indexed and publish completion event. |

Operational runbook:

1. Identify the failing request from logs or events using `requestUuid`, `organizationUuid`, and `documentUuid`.
2. Search logs for `Pipeline A graph failed` and read `failureStage` plus `failedNode`.
3. Inspect the document record in `organization_documents`:
   - `processingStatus`;
   - `indexingStatus`;
   - `lastError`;
   - `extractionRef`;
   - `documentType`;
   - `documentDomain`.
4. If checkpointing is enabled, inspect `edt_pipeline_a_graph_checkpoints` by `threadId=requestUuid`:
   - latest checkpoint `nodeId`;
   - latest checkpoint `nextNodeId`;
   - checkpoint state references only; do not expect raw text or structured payload JSON in the checkpoint document.
5. If large intermediate state is required, inspect `edt_pipeline_a_graph_artifacts` by request UUID, document UUID, and artifact type.
6. For Qdrant duplicate or partial-index suspicions:
   - verify the collection from the document or organization naming rule;
   - graph-path retry is safe because `upsertQdrant` deletes existing points by `documentUuid` before upsert.
7. Recovery options:
   - retry the same request with checkpointing enabled to resume from the latest checkpoint;
   - retry with checkpointing disabled to re-run the graph from the beginning;
   - set `enterprise-digital-twin.pipeline-a.graph-enabled=false` to roll back to the legacy imperative Pipeline A path.
8. Rollback policy:
   - do not delete checkpoint or artifact collections during rollback;
   - keep them available for diagnosis until the incident is closed;
   - remove or archive diagnostic records only through a separately approved retention/cleanup task.

Verification:

- Review logs from graph-path tests or local controlled run.
- Confirm no sensitive document text/payload appears in logs.
- Confirm failed node/stage can be identified without reading stack traces alone.

Executed verification:

- Passed: `mvn test -Dtest=EdtPipelineAGraphFactoryTest,EdtPipelineAGraphServiceTest,EdtPipelineAGraphParityTest`
  - Result: 13 tests passed.
  - Confirmed node failure wrapping exposes `nodeId` and `stage`.
  - Confirmed service warning logs include `requestUuid`, `organizationUuid`, `documentUuid`, `failureStage`, and `failedNode`.
  - Confirmed service warning logs do not print raw document text, normalized text, structured payload JSON, checkpoint payloads, or free-form exception messages.
- Passed: `mvn test -Dtest=EdtPipelineAStateTest,EdtPipelineAStateSerializerTest,MongoPipelineACheckpointSaverTest,EdtPipelineAArtifactComponentTest,EdtPipelineAGraphFactoryTest,EdtPipelineAGraphNodesTest,EdtPipelineAGraphServiceTest,EdtPipelineAGraphServiceResumeTest,EdtPipelineAGraphIdempotencyTest,EdtPipelineAGraphParityTest,EdtRequestFacadeProcessorGraphFlagTest,EdtPipelineADocumentIngestionServiceTest,QdrantUpsertAgentClientTest`
  - Result: 46 tests passed.
  - Note: LangGraph4j error logs during forced failure/interruption/Qdrant-failure tests are expected and covered by assertions.

Exit criteria:

- Operators can identify request UUID, organization UUID, document UUID, current stage, and failed node.
- Recovery/rollback steps are documented.

Confirmation checkpoint:

- Stop after Phase 8 and request approval to continue to Phase 9.

### Phase 9 - Controlled Rollout

Goal: enable the graph path in a controlled environment only after parity, resume, and observability are approved.

Scope:

- Enable `enterprise-digital-twin.pipeline-a.graph-enabled=true` only in local/dev or staging configuration, not production by default.
- Run controlled document ingestion with representative file types:
  - PDF;
  - DOCX;
  - TXT/Markdown if supported by existing parser routing;
  - unsupported/rejected file path.
- Compare persisted document state and UI events with legacy expectations.

Verification:

- Targeted Maven tests from Phases 3, 4, 6, and 7.
- Manual or automated controlled ingestion evidence from staging/local.
- Confirm rollback by setting `enterprise-digital-twin.pipeline-a.graph-enabled=false`.

Exit criteria:

- Controlled environment graph ingestion succeeds for representative documents.
- Rollback to legacy path is verified.
- Production remains disabled unless separately approved.

Confirmation checkpoint:

- Stop after Phase 9 and request approval before any production rollout.

Phase 9 execution log:

- Status: completed on 2026-07-02.
- Activities performed:
  - Re-reviewed the relevant `dev-guides` backend and agent structure guidelines before adding Phase 9 rollout artifacts.
  - Added `src/main/resources/application-dev.properties` as the controlled local/dev profile.
  - Enabled `enterprise-digital-twin.pipeline-a.graph-enabled=true` in the dev profile only.
  - Kept `enterprise-digital-twin.pipeline-a.graph-checkpoint-enabled=false` in the dev profile.
  - Confirmed the default `application.properties` keeps Pipeline A graph execution disabled by default, preserving production/default rollback behavior.
  - Added `EdtPipelineAGraphControlledRolloutTest` to provide automated controlled-ingestion evidence for representative parser routes:
    - PDF;
    - DOCX;
    - TXT;
    - Markdown;
    - unsupported/rejected file path.
  - The controlled rollout test executes the real sequential Pipeline A graph service/factory with mocked external agents and clients, then verifies processing/indexing side effects and completion events.
  - Confirmed rollback coverage through the existing facade graph flag tests and the default-disabled production property.
  - Manual staging ingestion was not executed in this phase; the evidence is automated local controlled ingestion with mocked external dependencies.
- Verification evidence:
  - Command: `mvn test -Dtest=EdtPipelineAGraphControlledRolloutTest`
  - Result: passed, 2 tests run, 0 failures, 0 errors, 0 skipped.
  - Command: `mvn test -Dtest=EdtPipelineAGraphControlledRolloutTest,EdtRequestFacadeProcessorGraphFlagTest -q`
  - Result: passed, 6 tests run, 0 failures, 0 errors, 0 skipped.
  - Command: `mvn test -Dtest=EdtPipelineAStateTest,EdtPipelineAStateSerializerTest,MongoPipelineACheckpointSaverTest,EdtPipelineAArtifactComponentTest,EdtPipelineAGraphFactoryTest,EdtPipelineAGraphNodesTest,EdtPipelineAGraphServiceTest,EdtPipelineAGraphServiceResumeTest,EdtPipelineAGraphIdempotencyTest,EdtPipelineAGraphParityTest,EdtRequestFacadeProcessorGraphFlagTest,EdtPipelineADocumentIngestionServiceTest,QdrantUpsertAgentClientTest,EdtPipelineAGraphControlledRolloutTest -q`
  - Result: passed, 48 tests run, 0 failures, 0 errors, 0 skipped.
  - Note: LangGraph4j error logs during forced failure/interruption/Qdrant-failure tests are expected and covered by assertions.
- Exit criteria result:
  - Controlled local/dev graph ingestion succeeds for representative document routes in automated test coverage.
  - Rollback to the legacy path is verified by the default-disabled property and facade flag tests.
  - Production/default configuration remains disabled unless separately approved.
- Next required action:
  - Wait for explicit approval before starting Phase 10 or any production rollout task.

### Phase 10 - Optional Parallelization

Goal: add safe parallelization only after the sequential graph has been accepted.

Scope:

- Identify safe fan-out candidates after idempotency is complete.
- Use Pipeline B's `node_async_virtual(...)` style only where blocking or expensive work benefits from virtual threads.
- Add deterministic fan-in ordering if any appender channels are introduced.
- Keep this phase separate from checkpoint/idempotency work.

Verification:

- `mvn test -Dtest=EdtPipelineAGraphParallelParityTest`
- Run Phase 4 parity tests again.
- Run idempotency/resume tests again if parallel nodes touch persisted state.

Exit criteria:

- Parallel graph output is identical to sequential graph output for fixed mocked inputs.
- No queue/node resource leaks occur in LLM-backed agents.
- Qdrant point ordering and persisted state remain deterministic.

Confirmation checkpoint:

- Stop after Phase 10 and request explicit approval before enabling parallel behavior outside test/dev.

Phase 10 execution log:

- Status: completed on 2026-07-02.
- Activities performed:
  - Re-reviewed the relevant `dev-guides` backend guidelines before changing graph execution behavior.
  - Assessed Pipeline A fan-out candidates and did not introduce artificial parallel graph branches because the current document flow has strict data dependencies:
    - parsing and normalization feed classification;
    - classification feeds structured extraction;
    - persisted extraction feeds chunking;
    - chunks feed embeddings;
    - embeddings feed Qdrant upsert;
    - Qdrant refs feed indexed-state commit.
  - Added an optional virtual-thread optimized graph build path in `EdtPipelineAGraphFactory`.
  - Kept the original sequential graph build path as the default behavior.
  - Applied the virtual-thread optimized path only to blocking or expensive nodes:
    - `parseDocument`;
    - `normalizeText`;
    - `classifyDocument`;
    - `extractStructuredPayload`;
    - `chunkDocument`;
    - `embedChunks`;
    - `upsertQdrant`.
  - Left persistence/status/event nodes on the regular sequential async path.
  - Added `enterprise-digital-twin.pipeline-a.graph-virtual-threads-enabled=false` to default configuration.
  - Enabled `enterprise-digital-twin.pipeline-a.graph-virtual-threads-enabled=true` only in `application-dev.properties`.
  - Updated `EdtPipelineAGraphService` to select the virtual-thread optimized graph only when the new flag is enabled.
  - Added `EdtPipelineAGraphParallelParityTest` to compare sequential and virtual-thread optimized graph final state for fixed mocked inputs.
  - Added service-level coverage proving the new flag routes to `buildVirtualThreadOptimized()`.
  - Updated controlled rollout coverage to assert dev enables graph virtual-thread execution.
- Verification evidence:
  - Command: `mvn test -Dtest=EdtPipelineAGraphParallelParityTest -q`
  - Result: passed, 1 test run, 0 failures, 0 errors, 0 skipped.
  - Command: `mvn test -Dtest=EdtPipelineAGraphControlledRolloutTest -q`
  - Result: passed, 2 tests run, 0 failures, 0 errors, 0 skipped.
  - Command: `mvn test -Dtest=EdtPipelineAGraphParallelParityTest,EdtPipelineAGraphParityTest,EdtPipelineAGraphIdempotencyTest,EdtPipelineAGraphServiceResumeTest -q`
  - Result: passed, 9 tests run, 0 failures, 0 errors, 0 skipped.
  - Command: `mvn test -Dtest=EdtPipelineAGraphServiceTest,EdtPipelineAGraphFactoryTest,EdtPipelineAGraphParallelParityTest -q`
  - Result: passed, 10 tests run, 0 failures, 0 errors, 0 skipped.
  - Note: LangGraph4j error logs during forced failure/interruption/Qdrant-failure tests are expected and covered by assertions.
- Exit criteria result:
  - Virtual-thread optimized graph output is identical to sequential graph output for fixed mocked inputs.
  - No appender channels or fan-in ordering were introduced, so Qdrant point ordering and persisted-state ordering remain unchanged.
  - Production/default configuration remains disabled for graph virtual-thread execution unless separately approved.
- Next required action:
  - Wait for explicit approval before enabling any broader parallel behavior or production rollout.

### Phase 11 - Production Rollout Readiness Gate

Goal: add a final safety gate before any production rollout, without enabling production graph execution.

Scope:

- Confirm the default profile still keeps Pipeline A graph execution disabled.
- Confirm checkpointing and virtual-thread optimization remain disabled in the default profile.
- Confirm local/dev is the only checked-in profile that enables Pipeline A graph execution.
- Keep this phase limited to rollout readiness evidence and tests.
- Do not enable production graph execution.
- Do not remove the legacy Pipeline A service.

Verification:

- `mvn test -Dtest=EdtPipelineAGraphProductionReadinessTest`
- Run the Phase 9/10 controlled rollout and parity tests again.

Exit criteria:

- Default configuration is verified as rollback-safe.
- Dev-only graph enablement is verified.
- Production rollout still requires a separate explicit approval and environment-specific configuration change.

Confirmation checkpoint:

- Stop after Phase 11 and request explicit approval before any production rollout.

Phase 11 execution log:

- Status: completed on 2026-07-02.
- Activities performed:
  - Added `EdtPipelineAGraphProductionReadinessTest`.
  - Verified default `application.properties` keeps:
    - `enterprise-digital-twin.pipeline-a.graph-enabled=false`;
    - `enterprise-digital-twin.pipeline-a.graph-checkpoint-enabled=false`;
    - `enterprise-digital-twin.pipeline-a.graph-virtual-threads-enabled=false`;
    - `enterprise-digital-twin.pipeline-a.graph-timeout-seconds=600`.
  - Verified checked-in dev profile keeps graph execution enabled only for local/dev rollout while checkpointing remains disabled.
  - Confirmed Phase 11 does not enable production graph execution and does not remove the legacy service.
- Verification evidence:
  - Command: `mvn test -Dtest=EdtPipelineAGraphProductionReadinessTest`
  - Result: passed, 2 tests run, 0 failures, 0 errors, 0 skipped.
  - Command: `mvn test -Dtest=EdtPipelineAGraphProductionReadinessTest,EdtPipelineAGraphControlledRolloutTest,EdtPipelineAGraphParallelParityTest,EdtPipelineAGraphParityTest,EdtRequestFacadeProcessorGraphFlagTest -q`
  - Result: passed, 14 tests run, 0 failures, 0 errors, 0 skipped.
  - Note: LangGraph4j error logs during forced failure/interruption/Qdrant-failure parity tests are expected and covered by assertions.
- Exit criteria result:
  - Default configuration is verified as rollback-safe.
  - Dev-only graph enablement is verified.
  - Production rollout still requires separate explicit approval and environment-specific configuration.
- Next required action:
  - Wait for explicit approval before production rollout.

---

## 13. Test Plan

Add tests mirroring Pipeline B graph coverage:

- `EdtPipelineAStateTest`
  - defaults are correct;
  - base channels overwrite values;
  - future appender channels accumulate deterministically if introduced.
- `EdtPipelineAGraphFactoryTest`
  - graph compiles;
  - expected nodes/edges execute in order for Phase 1.
- Node tests
  - each node maps inputs to outputs and returns only keys declared in `EdtPipelineAState.SCHEMA`;
  - no node logs document text or payload JSON.
- `EdtPipelineAGraphServiceTest`
  - happy path;
  - timeout;
  - interruption;
  - execution failure marks failed and publishes failed event;
  - resume path when checkpoint exists.
- `EdtRequestFacadeProcessorGraphFlagTest`
  - Pipeline A graph flag selects graph service;
  - disabled flag preserves legacy service.
- Integration-style parity test with mocked agents/clients
  - legacy service and graph service receive the same request and mocked outputs;
  - final document status, indexing status, document type/domain, structured payload, and event calls match.

---

## 14. Rollout Strategy

1. Merge graph code with `enterprise-digital-twin.pipeline-a.graph-enabled=false`.
2. Enable graph path in local/dev with mocked or controlled documents.
3. Enable sequential graph in staging without checkpointing.
4. Enable checkpointing in staging after idempotency decisions are implemented.
5. Enable graph path in production for a limited organization/document subset if runtime configuration supports scoped rollout.
6. Keep the legacy service for at least one release after production graph rollout.

Rollback:

- Set `enterprise-digital-twin.pipeline-a.graph-enabled=false`.
- Keep checkpoint collections read-only for investigation; do not delete automatically during rollback.

---

## 15. Open Decisions

- Closed in Phase 5: `EdtExtractionPersistenceComponent.saveExtractionJson(...)` should persist the generated or reused `extractionRef` into `OrganizationDocumentDto.extractionRef`.
- Closed in Phase 5: Pipeline A checkpointing should use a hybrid artifact-reference strategy. Checkpoint documents store small graph state and references; large raw text, normalized text, and structured payload JSON are not stored directly in production checkpoint payloads.
- Closed in Phase 5: Qdrant resume idempotency should use delete-then-upsert by `documentUuid` for the current LangChain4j embedding-store path. Deterministic point IDs are deferred as optional future hardening.
- Closed in Phase 5: `StructuredExtractionAgentClient` does not need to become an interface before this migration continues.
- Closed in Phase 5: Dedicated Pipeline A graph `AgentRuntimeEventPublisher` events are deferred; existing lifecycle and MQTT events are sufficient for the next phases.

---

## 16. Definition of Done

- Pipeline A graph path is feature-flagged and disabled by default until parity is proven.
- Legacy Pipeline A remains available as fallback.
- Graph state, nodes, factory, service, and exceptions follow existing Pipeline B patterns.
- All node outputs are declared in `EdtPipelineAState.SCHEMA`.
- Failure handling marks documents failed and publishes failure events exactly as the legacy path does.
- Tests cover graph selection, happy path, failure path, interruption, and checkpoint resume.
- Logs and persisted error messages avoid document text, structured payloads, prompts, and secrets.
- `mvn test` or targeted Maven tests pass before enabling the graph flag.
