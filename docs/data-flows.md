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
    Article["ArticleDto"]
    Document["DocumentDto (planned)"]
    Post["PostDto / MessageDto (planned)"]

    Raw --> Mime
    Mime -->|"text/html"| Html
    Mime -->|"application/pdf"| Pdf
    Mime -->|"application/json"| Api
    Html --> Article
    Pdf --> Document
    Api --> Post
```

Status: DTO boundary defined; parsers planned.

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

    Article0 --> Taxonomy
    Taxonomy --> Entities
    Entities --> Claims
    Entities --> Events
    Claims --> Assessment
    Events --> Assessment
    Assessment --> Embedding
    Embedding --> Provenance
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
