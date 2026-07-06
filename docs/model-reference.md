# Model Reference

## SourceDto

Represents an operational OSINT source.

Collection: `sources`

Key fields:

- `id`
- `name`
- `type`
- `endpoint`
- `description`
- `status`
- `priority`
- `polling_interval`
- `last_successful_run`
- `last_execution`
- `last_content_timestamp`
- `authentication`
- `configuration`
- `tags`

Supported source types:

- `WEBSITE`
- `RSS`
- `SITEMAP`
- `TELEGRAM`
- `X`
- `FACEBOOK`
- `YOUTUBE`
- `PDF`
- `EMAIL`
- `API`
- `FILESYSTEM`
- `DATABASE`
- `MANUAL`
- `DISCORD`
- `MASTODON`
- `BLUESKY`
- `REDDIT`
- `DARK_WEB`
- `TOR`
- `RSS_CUSTOM`

## AuthenticationDto

Represents source access credentials.

Fields:

- `type`
- `username`
- `password`
- `api_key`
- `bearer_token`

Supported authentication types:

- `NONE`
- `BASIC`
- `API_KEY`
- `BEARER_TOKEN`
- `OAUTH2`
- `SESSION_COOKIE`
- `CUSTOM`

Security rule:

Authentication values must be treated as sensitive and excluded from logs and diagnostic API responses.

## RawDocumentDto

Represents acquired raw content, independent of source type.

Collection: `raw_documents`

Fields:

- `id`
- `source_id`
- `original_uri`
- `acquisition_time`
- `content_timestamp`
- `mime_type`
- `raw_content`
- `content_hash`
- `metadata`

Examples of raw content:

- HTML page
- RSS item content
- Telegram message payload
- PDF bytes
- email body
- REST JSON response
- local filesystem document

## ArticleDto

Represents a structured intelligence article derived from a raw document.

Collection: `articles`

Implements:

- `StructuredDocument`

Top-level fields:

- `id`
- `raw_document_id`
- `metadata`
- `taxonomy`
- `entities`
- `relationships`
- `events`
- `intelligence_assessment`
- `assessment`
- `embedding`
- `provenance`
- `links`
- `claims`

Important boundary:

`ArticleDto` does not contain source details. Source traceability goes through `raw_document_id -> RawDocumentDto.source_id -> SourceDto.id`.

## StructuredDocument

Marker interface for parser outputs that can enter a workflow context.

Package:

```text
it.osint.raven.workflow.StructuredDocument
```

Current implementation:

- `ArticleDto`

Planned examples:

- `TelegramMessageDto`
- `PdfDocumentDto`
- `EmailDocumentDto`
- `ApiPayloadDto`

The interface exists so Raven workflows can operate on structured documents without assuming that every document is an article. A parser can produce any domain DTO that implements `StructuredDocument`, and the workflow layer can carry it through `WorkflowContext`.

## WorkflowContext

Shared execution state for workflow nodes and workflow agents.

Package:

```text
it.osint.raven.workflow.WorkflowContext
```

Core fields:

- `workflowId`
- `workflowName`
- `startedAt`
- `updatedAt`
- `source`
- `rawDocument`
- `document`
- `outputs`
- `variables`
- `events`
- `warnings`
- `errors`
- `metrics`
- `status`

The context is independent from Spring, LangGraph4j, MongoDB, Neo4j and Qdrant. It is a domain model object that can be passed by any orchestration layer.

### WorkflowStatus

Supported status values:

- `CREATED`
- `RUNNING`
- `COMPLETED`
- `FAILED`
- `PARTIAL`

`PARTIAL` means the workflow produced useful outputs but one or more nodes failed, degraded or skipped optional work.

### WorkflowArtifact

Shared outputs are stored as artifacts:

```text
id
type
value
producedBy
producedAt
```

The output map is:

```java
Map<Class<?>, WorkflowArtifact>
```

This legacy/type lookup avoids adding new fields to `WorkflowContext` for every agent result. Capability-based lookup is preferred for workflow node dependencies because it also distinguishes outputs that share the same Java type.

Example outputs:

- `MetadataDto`
- `TaxonomyDto`
- `List<EntityDto>`
- `AssessmentDto`
- extraction result DTOs introduced by future nodes

API:

```java
context.put(metadata);
context.put("taxonomy-agent", taxonomy);
context.put("entity-agent", ENTITY_EXTRACTION, entityExtractionResult);

Optional<MetadataDto> metadata = context.get(MetadataDto.class);
TaxonomyDto taxonomy = context.require(TaxonomyDto.class);
EntityExtractionResult entities = context.require(ENTITY_EXTRACTION);
boolean hasAssessment = context.contains(ASSESSMENT);
```

### WorkflowEvent

Audit event attached to a workflow execution:

```text
timestamp
node
type
message
```

`WorkflowEventType` includes lifecycle events, node events, output events, warning/error events, metric events, variable events and status changes.

### WorkflowError

Structured error attached to a workflow execution:

```text
node
exception
message
timestamp
```

The `exception` value is the exception class name or code, not a serialized `Throwable`.

See [Workflow context](workflow-context.md) for the full design explanation and usage rules.

## WorkflowNode

Engine-independent contract for a single executable workflow step.

Package:

```text
it.osint.raven.workflow.WorkflowNode
```

Core methods:

```java
String id();
String name();
String description();
WorkflowNodeCategory category();
Set<WorkflowCapability> requires();
Set<WorkflowCapability> produces();
WorkflowContext execute(WorkflowContext context) throws Exception;
```

`WorkflowNode` is deliberately a domain interface. It depends on `WorkflowContext`, not on LangGraph4j or Spring. `SequentialWorkflowEngine` can execute registered nodes through an `ExecutionPlan`, and a future engine can adapt the same nodes into a DAG, but the node itself should not know which engine executes it.

The most important part of the contract is the capability declaration:

- `requires()` lists named capabilities that must already be present in `WorkflowContext`.
- `produces()` lists named capabilities the node may publish.

`WorkflowCapability` contains:

```text
id
namespace
description
type
version
required
aliases
```

The capability identity is `namespace + id + version`. A node should be able to declare `osint:entity-extraction@2.0.0` without making `EntityDto.class` the dependency key. The Java `type` only validates and casts the artifact value inside the context layer. The `version` lets Raven evolve payload contracts over time. The `required` flag distinguishes input declarations from output declarations. `aliases` support compatible names such as `entities`, `ner` or `entity-extraction`.

The default `canExecute(context)` implementation checks every required capability with `context.contains(capability)`.

Default runtime policy metadata:

```text
configuration  empty map
timeout        PT5M
maxRetries     0
parallelizable true
idempotent     true
priority       100
```

These values are declarations for the orchestration layer. The interface itself does not enforce timeouts, retries or scheduling.

### WorkflowNodeCategory

Supported categories:

- `CONNECTOR`
- `PARSER`
- `ENRICHMENT`
- `AI`
- `PERSISTENCE`
- `VALIDATION`
- `UTILITY`
- `EXPORT`

Categories are for discovery and operator understanding. Dependency ordering should be based on `requires()` and `produces()`.

See [Workflow nodes](workflow-nodes.md) for the full contract guide.

## Article Enrichment Levels

`MetadataDto`

- `title`
- `subtitle`
- `author`
- `publication_date`
- `category`
- `tags`
- `images`
- `attachments`

`TaxonomyDto`

- `domain`
- `sub_domain`
- `event_type`
- `sector`
- `impact_level`
- `topics`
- `keywords`

`EntityDto`

- `id`
- `type`
- `name`
- `normalized_name`
- `wikidata_id`
- `confidence`

`RelationshipDto`

- `source`
- `target`
- `predicate`
- `confidence`

`EventDto`

- `id`
- `type`
- `date`
- `description`
- `participants`
- `locations`

`ClaimDto`

- `id`
- `source_entity_id`
- `statement`
- `target_entity_ids`
- `date`
- `type`
- `confidence`
- `evidence`

`EvidenceDto`

- `id`
- `type`
- `source`
- `url`
- `excerpt`
- `locator`
- `confidence`

## Mongo Indexes

`sources`

- unique sparse `name`
- `type + endpoint`
- `status + priority`
- `tags`

`raw_documents`

- unique sparse `source_id + original_uri`
- unique sparse `source_id + content_hash`
- `acquisition_time`
- `content_timestamp`
- `mime_type`

`articles`

- unique sparse `raw_document_id`
- `metadata.publication_date`
- `taxonomy.domain + taxonomy.sub_domain + taxonomy.event_type`
- `entities.normalized_name + entities.type`
- `events.type + events.date`

## JSON Contract

DTO fields exposed to JSON and Mongo payloads use `snake_case`.

Examples:

- `polling_interval`
- `last_successful_run`
- `source_id`
- `raw_document_id`
- `publication_date`
- `impact_level`
- `normalized_name`
- `source_entity_id`
- `target_entity_ids`
- `extraction_time`
