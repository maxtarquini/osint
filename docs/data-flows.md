# Data Flows

## High-Level Acquisition Flow

```mermaid
sequenceDiagram
    participant Scheduler
    participant SourceRepo as SourceRepository
    participant Connector as SourceConnector
    participant RawRepo as RawDocumentRepository

    Scheduler->>SourceRepo: findEnabledOrderedByPriority(limit)
    SourceRepo-->>Scheduler: SourceDto[]
    Scheduler->>Connector: fetch(source)
    Connector-->>Scheduler: RawDocumentDto[]
    Scheduler->>RawRepo: save(rawDocument)
    RawRepo-->>Scheduler: persisted RawDocumentDto
```

Status: repository and connector interface implemented; scheduler and concrete connectors planned.

## Parsing Flow

```mermaid
flowchart TD
    Raw["RawDocumentDto"]
    Mime{"mime_type"}
    Html["HtmlParser"]
    Pdf["PdfParser"]
    Api["JsonParser / ApiParser"]
    Structured["StructuredDocument"]
    Article["ArticleDto"]
    Document["PdfDocumentDto (planned)"]
    Post["TelegramMessageDto / MessageDto (planned)"]

    Raw --> Mime
    Mime -->|"text/html"| Html
    Mime -->|"application/pdf"| Pdf
    Mime -->|"application/json"| Api
    Html --> Article
    Pdf --> Document
    Api --> Post
    Article --> Structured
    Document --> Structured
    Post --> Structured
```

Status: DTO boundary defined; parsers planned.

## Workflow Context and Node Flow

`WorkflowContext` is the state carrier between parser output and enrichment/persistence nodes. `WorkflowNode` is the common contract implemented by those executable steps.

```mermaid
sequenceDiagram
    participant Parser
    participant Context as WorkflowContext
    participant Metadata as Metadata WorkflowNode
    participant Entity as Entity WorkflowNode
    participant Assessment as Assessment WorkflowNode
    participant Store as Persistence Adapter

    Parser->>Context: document(StructuredDocument)
    Parser->>Context: put(structured-document)
    Metadata->>Metadata: requires structured-document
    Metadata->>Metadata: produces metadata-extraction
    Metadata->>Context: put(MetadataDto)
    Entity->>Entity: requires structured-document
    Entity->>Entity: produces entity-extraction
    Entity->>Context: put(EntityExtractionResult)
    Assessment->>Context: require(metadata-extraction)
    Assessment->>Context: put(AssessmentDto)
    Store->>Context: read document + outputs + metrics
```

The context and node flow is separate from the workflow engine. It is the engine-independent domain model that `SequentialWorkflowEngine` already passes between nodes, and that future runtime adapters can also use.

Shared outputs are stored as `WorkflowArtifact` values. This means Raven can later answer questions such as "which node produced this taxonomy?" or "when were these entities extracted?" without adding provenance fields to every DTO.

The node contract adds one more piece: nodes declare named capabilities through `requires()` and `produces()`. That makes dependency order explicit and gives `WorkflowCompiler` enough information to build an `ExecutionPlan` without hard-coding every pipeline or guessing from Java classes.

Status: `WorkflowContext`, `WorkflowArtifact`, `WorkflowNode`, `WorkflowNodeCategory`, `WorkflowCompiler`, `WorkflowEngine`, `SequentialWorkflowEngine` and tests implemented; concrete production nodes and LangGraph4j adapter planned.

## Article Enrichment Flow

```mermaid
flowchart LR
    Article0["ArticleDto raw_document_id + metadata"]
    Taxonomy["Taxonomy"]
    Entities["Entities"]
    Claims["Claims + Evidence"]
    Events["Events"]
    Assessment["Assessment"]
    Embedding["Embedding"]
    Provenance["Provenance"]
    Context["WorkflowContext outputs"]

    Article0 --> Taxonomy
    Taxonomy --> Entities
    Entities --> Claims
    Entities --> Events
    Claims --> Assessment
    Events --> Assessment
    Assessment --> Embedding
    Embedding --> Provenance
    Taxonomy --> Context
    Entities --> Context
    Claims --> Context
    Events --> Context
    Assessment --> Context
    Embedding --> Context
```

Status: DTO model implemented; enrichment pipeline planned.

## Persistence Flow

```mermaid
flowchart TD
    SourceDto["SourceDto"]
    RawDocumentDto["RawDocumentDto"]
    ArticleDto["ArticleDto"]
    Mongo["MongoDB database: raven"]
    Sources["sources"]
    RawDocuments["raw_documents"]
    Articles["articles"]

    SourceDto --> Sources
    RawDocumentDto --> RawDocuments
    ArticleDto --> Articles
    Sources --> Mongo
    RawDocuments --> Mongo
    Articles --> Mongo
```

Implemented collections:

- `sources`
- `raw_documents`
- `articles`

## Traceability Flow

```mermaid
flowchart BT
    Article["ArticleDto"]
    RawDocument["RawDocumentDto"]
    Source["SourceDto"]
    Evidence["EvidenceDto"]
    Claim["ClaimDto"]
    Provenance["ProvenanceDto"]

    Article -->|"raw_document_id"| RawDocument
    RawDocument -->|"source_id"| Source
    Claim --> Evidence
    Article --> Claim
    Article --> Provenance
```

This flow is central for intelligence use cases: every structured assertion should be traceable back to the raw document, the configured source and the extraction method.

## Deduplication Points

Raw document duplicate control is designed around:

- `source_id + original_uri`;
- `source_id + content_hash`.

Article duplicate control is modeled separately through:

- `assessment.duplicate`;
- unique `raw_document_id` index in the `articles` collection.

Future duplicate detection can compare:

- canonical URLs;
- content hashes;
- embeddings;
- normalized titles;
- event/entity overlap.
