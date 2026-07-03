# Workflow Nodes

## Purpose

`WorkflowNode` is the domain contract that every Raven workflow node must implement.

It describes a single processing step in an OSINT workflow: a connector, a parser, an enrichment step, an AI extraction step, a validation step, a persistence adapter or an export operation. The important point is that all of those steps expose the same shape to the future workflow engine.

The class lives in:

```text
it.osint.raven.workflow.WorkflowNode
```

Node categories are represented by:

```text
it.osint.raven.workflow.WorkflowNodeCategory
```

The contract is intentionally small and engine-independent. A node knows about `WorkflowContext` and named `WorkflowCapability` declarations; it does not know about LangGraph4j, Spring, MongoDB, Neo4j, Qdrant or any concrete orchestration technology. This keeps the domain layer clean and allows the runtime engine to evolve without forcing every node implementation to change.

## Why This Contract Exists

Raven workflows are expected to grow into DAGs made of many specialized steps:

- website connectors;
- RSS connectors;
- Telegram connectors;
- HTML parsers;
- PDF parsers;
- metadata extraction;
- taxonomy classification;
- entity extraction;
- relationship extraction;
- claim extraction;
- event extraction;
- embedding generation;
- Neo4j persistence;
- MongoDB persistence;
- Qdrant persistence;
- exports and validation steps.

Without a common node contract, every orchestration layer would need custom code for each step. `WorkflowNode` gives Raven a single vocabulary: every node declares who it is, what it needs, what it produces and how it executes against a shared `WorkflowContext`.

That declaration is what will later allow the workflow engine to build a DAG from dependencies. A relationship extraction node should not say only "I need some `List`" or "I need some `EntityDto`"; it should say "I need capability `entity-extraction`, version `1.0.0`, whose value type is `EntityExtractionResult`". That makes the dependency precise even when several nodes produce values backed by similar Java types.

## Engine Independence

`WorkflowNode` must remain independent from:

- LangGraph4j;
- Spring;
- MongoDB;
- Neo4j;
- Qdrant;
- framework-specific serializers;
- concrete model clients;
- repositories or database handles.

The future LangGraph4j layer may adapt `WorkflowNode` implementations into LangGraph4j graph nodes, but that adapter belongs outside the domain contract. The direction of dependency is important:

```text
LangGraph4j adapter -> WorkflowNode -> WorkflowContext
```

The inverse direction is not allowed:

```text
WorkflowNode -> LangGraph4j
```

This boundary is the same design principle already used by `WorkflowContext`: the workflow package describes Raven domain state and node behavior, not the engine that happens to run it.

## Contract Summary

Every node must implement:

```java
String id();
String name();
String description();
WorkflowNodeCategory category();
Set<WorkflowCapability> requires();
Set<WorkflowCapability> produces();
WorkflowContext execute(WorkflowContext context) throws Exception;
```

The execution method receives the shared context, reads upstream artifacts, adds new artifacts or execution observations, and returns the same enriched context:

```java
WorkflowContext execute(WorkflowContext context) throws Exception;
```

Nodes should use:

- `context.require(...)` for mandatory inputs;
- `context.get(...)` for optional inputs;
- `context.contains(capability)` when they need to check availability;
- `context.put(...)` to publish domain outputs;
- `context.event(...)` for lifecycle trace;
- `context.metric(...)` for counts, latency and resource usage;
- `context.warning(...)` for recoverable degraded behavior;
- `context.error(...)` for failures that should remain visible after execution.

## Node Identity

`id()` returns the unique stable identifier used by workflow definitions, engine logs and artifact provenance.

Example:

```java
@Override
public String id() {
    return "metadata-extractor";
}
```

The id should be stable across releases. It is not a UI label and should not change casually, because future workflow definitions, traces and persisted execution records may refer to it.

`name()` returns the human-readable name:

```java
@Override
public String name() {
    return "Metadata Extraction";
}
```

`description()` gives a short explanation of what the node does. It should be useful for documentation, discovery screens and debugging, but it should not include runtime secrets or large prompt text.

## Categories

`WorkflowNodeCategory` has the following values:

```text
CONNECTOR
PARSER
ENRICHMENT
AI
PERSISTENCE
VALIDATION
UTILITY
EXPORT
```

Categories are deliberately broad. They are not meant to encode every subtype. A website connector and an RSS connector are both `CONNECTOR`; their precise identity belongs in `id()`, `name()`, `description()` and future configuration metadata.

Use the categories as follows:

| Category | Use for |
|---|---|
| `CONNECTOR` | Nodes that acquire content or events from external sources. |
| `PARSER` | Nodes that convert raw content into structured workflow artifacts. |
| `ENRICHMENT` | Deterministic processors that add derived fields or normalize existing data. |
| `AI` | Model-driven extraction, classification, summarization or reasoning steps. |
| `PERSISTENCE` | Nodes that write artifacts or projections to storage systems. |
| `VALIDATION` | Nodes that check invariants, quality gates or required state. |
| `UTILITY` | Supporting workflow operations that do not fit a domain-specific category. |
| `EXPORT` | Nodes that emit workflow results to external formats or destinations. |

## Capability Declaration

The most important part of the contract is the capability declaration:

```java
Set<WorkflowCapability> requires();
Set<WorkflowCapability> produces();
```

`requires()` declares the named capabilities that must already exist in `WorkflowContext` before a node can execute.

`produces()` declares the named capabilities that the node may add to the context.

`WorkflowCapability` is a nominal contract value:

```java
record WorkflowCapability(
        String id,
        String namespace,
        String description,
        Class<?> type,
        Version version,
        boolean required,
        Set<String> aliases
)
```

Raven uses `java.lang.module.ModuleDescriptor.Version` for the current version field. The default helper methods use version `1.0.0`.

The fields have distinct jobs:

| Field | Purpose |
|---|---|
| `id` | Stable logical capability name, for example `entity-extraction` or `organization-resolution`. |
| `namespace` | Collision boundary, for example `core`, `osint`, `nlp`, `graph` or `rag`. |
| `description` | Short human-readable explanation of the contract. |
| `type` | Runtime Java value type used only for validation and safe casts. |
| `version` | Contract version for evolving capability payloads over time. |
| `required` | Whether the capability describes an input requirement rather than an output. |
| `aliases` | Alternate logical ids accepted for compatibility or discovery, for example `entities` or `ner`. |

The capability identity is `namespace + id + version`. The Java type is metadata for validation and casting, not the dependency key. Equality intentionally ignores Java type, description, aliases and the required/produced direction.

This means a node can declare:

```text
requires -> osint:entity-extraction@2.0.0
```

instead of forcing the engine to infer intent from `EntityDto.class`.

Example:

```java
private static final WorkflowCapability STRUCTURED_DOCUMENT =
        WorkflowCapability.required("structured-document", StructuredDocument.class);

private static final WorkflowCapability METADATA =
        WorkflowCapability.builder()
                .namespace("osint")
                .id("metadata")
                .description("Extracted document metadata")
                .type(MetadataDto.class)
                .aliases(Set.of("metadata-extraction"))
                .build();

@Override
public Set<WorkflowCapability> requires() {
    return Set.of(STRUCTURED_DOCUMENT);
}

@Override
public Set<WorkflowCapability> produces() {
    return Set.of(METADATA);
}
```

The declaration is not just documentation. It is the future bridge between modular node registration and DAG construction. A workflow engine can inspect all registered nodes, compare required capabilities with produced capabilities, and derive a valid execution order.

`WorkflowRegistry` is the central place where nodes are registered and queried by those declarations. It can answer questions such as "which nodes produce `osint:metadata@1.0.0`?" and "which nodes require `core:structured-document@1.0.0`?" without involving LangGraph4j.

Capabilities expose helper methods for nominal matching:

```java
String qualifiedName();          // namespace:id@version
boolean matches(...);            // namespace/id-or-alias/version match
boolean supportsAlias(String);   // alias lookup
```

`requires()` is evaluated against capability artifacts, not arbitrary fields. For example, `WorkflowContext` has a `document` field, but a node that requires `structured-document` expects that document to be present under the same capability id:

```java
context
        .document(article)
        .put("html-parser", STRUCTURED_DOCUMENT, article);
```

This small duplication is intentional. The field gives the run a convenient current-document pointer; the capability artifact gives the DAG engine an explicit dependency surface.

For example:

```text
HTML Parser
  produces structured-document -> StructuredDocument

Metadata Extraction
  requires structured-document -> StructuredDocument
  produces metadata-extraction -> MetadataDto

Entity Extraction
  requires structured-document -> StructuredDocument
  produces entity-extraction -> EntityExtractionResult

Relationship Extraction
  requires entity-extraction -> EntityExtractionResult
  produces relationship-extraction -> RelationshipExtractionResult
```

From those declarations, an engine can see that relationship extraction cannot run before entity extraction, while metadata extraction and entity extraction may be candidates for parallel execution once a structured document exists.

## canExecute

`WorkflowNode` provides a default dependency check:

```java
default boolean canExecute(WorkflowContext context)
```

The implementation verifies that every declared requirement is present in the context:

```java
return requires().stream().allMatch(context::contains);
```

This intentionally uses `WorkflowContext.contains(WorkflowCapability)`. It does not inspect fields, annotations, constructor parameters or framework metadata. The rule is simple: if a node declares a required capability id and type, that capability must be available in the context.

This avoids the common collision where two nodes share a Java type:

```text
EntityExtractionNode
  produces entity-extraction -> EntityExtractionResult

OrganizationResolutionNode
  produces organization-resolution -> EntityResolutionResult
```

Even if both results were represented internally as lists, the engine would still see two different capabilities.

This keeps dependency checking predictable and easy to test.

## Configuration

Some nodes need configuration. For example:

- maximum RSS items;
- parser mode;
- taxonomy namespace;
- model name;
- embedding dimensions;
- Qdrant collection;
- export format.

The contract exposes:

```java
default Map<String, Object> configuration()
```

By default it returns an empty map. This method is metadata, not dependency injection. It should not return live clients, repositories, services, open files, queues or framework-managed objects.

Configuration values should be safe to inspect. Do not include passwords, bearer tokens, API keys, raw prompts, full document text or full LLM payloads.

## Lifecycle Hooks

The interface provides optional hooks:

```java
default void beforeExecute(WorkflowContext context)
default void afterExecute(WorkflowContext context)
default void onError(WorkflowContext context, Exception ex)
```

These are hooks for a workflow engine or adapter to call around `execute`. They are intentionally no-ops by default.

A future engine can use this sequence:

```text
beforeExecute(context)
execute(context)
afterExecute(context)
```

On failure:

```text
beforeExecute(context)
execute(context) throws Exception
onError(context, ex)
```

Node implementations may use the hooks to record context events or metrics, but they should not assume a specific engine. The engine remains responsible for retry policy, timeout handling, scheduling and global workflow status decisions.

## Timeout and Retry Policy

Each node can declare runtime preferences:

```java
default Duration timeout() {
    return Duration.ofMinutes(5);
}

default int maxRetries() {
    return 0;
}
```

These values are declarations. The domain contract does not enforce timeouts or retries by itself. A future engine will read them and decide how to apply them.

The default timeout is five minutes. The default retry count is zero. This is intentionally conservative: retrying AI calls, persistence operations or connector fetches can create duplicate side effects unless a node is explicitly designed to be idempotent.

## Parallelization

Nodes declare whether they are safe candidates for parallel scheduling:

```java
default boolean parallelizable() {
    return true;
}
```

This does not mean the engine must run the node in parallel. It means the node does not opt out of parallel execution.

A node should return `false` when it:

- mutates shared state outside `WorkflowContext`;
- depends on a strict ordering not captured by `requires()`;
- writes to an external system in a way that cannot tolerate concurrent execution;
- uses non-thread-safe collaborators;
- relies on a resource that must be serialized.

Even when `parallelizable()` returns `true`, the engine must still respect dependency ordering and avoid unsafe writes to the same capability when that matters for the workflow.

## Idempotency

Nodes declare whether repeated execution with the same context is expected to be safe:

```java
default boolean idempotent() {
    return true;
}
```

Idempotency matters for retries, checkpoint resume and failure recovery.

A pure metadata extraction node that replaces a `MetadataDto` output can usually be idempotent. A persistence node that inserts a new row or emits a webhook may not be idempotent unless it uses stable ids, deduplication keys or upsert semantics.

If a node is not idempotent, override the default:

```java
@Override
public boolean idempotent() {
    return false;
}
```

Future engines should treat non-idempotent nodes carefully: avoid blind retries, use explicit compensation logic, or require external deduplication.

## Priority

Nodes can declare a priority:

```java
default int priority() {
    return 100;
}
```

Priority is useful when more than one node can satisfy the same capability. For example, Raven may eventually have multiple entity extractors:

- a fast rule-based extractor;
- a local model extractor;
- a remote LLM extractor;
- a high-accuracy but expensive extractor.

The engine can use priority to choose between equivalent nodes, or to order candidates before applying additional policy.

The default priority is `100`. Lower values may be treated as more preferred by future engines, but the current domain contract only exposes the value; it does not define engine selection semantics.

## Example Implementation

```java
public final class MetadataExtractionNode implements WorkflowNode {

    private static final WorkflowCapability STRUCTURED_DOCUMENT =
            WorkflowCapability.required("structured-document", StructuredDocument.class);

    private static final WorkflowCapability METADATA =
            WorkflowCapability.produced("metadata-extraction", MetadataDto.class);

    @Override
    public String id() {
        return "metadata-extractor";
    }

    @Override
    public String name() {
        return "Metadata Extraction";
    }

    @Override
    public String description() {
        return "Extracts article metadata from a structured document.";
    }

    @Override
    public WorkflowNodeCategory category() {
        return WorkflowNodeCategory.ENRICHMENT;
    }

    @Override
    public Set<WorkflowCapability> requires() {
        return Set.of(STRUCTURED_DOCUMENT);
    }

    @Override
    public Set<WorkflowCapability> produces() {
        return Set.of(METADATA);
    }

    @Override
    public WorkflowContext execute(WorkflowContext context) throws Exception {
        context.event(id(), WorkflowEventType.NODE_STARTED, "Metadata extraction started");

        StructuredDocument document = context.require(STRUCTURED_DOCUMENT);
        MetadataDto metadata = extractMetadata(document);

        return context
                .put(id(), METADATA, metadata)
                .metric("metadata_fields_found", countFields(metadata))
                .event(id(), WorkflowEventType.NODE_COMPLETED, "Metadata extraction completed");
    }
}
```

The example shows the intended style:

- the node declares its requirements;
- it reads its input from `WorkflowContext`;
- it publishes an output with `id()` as producer;
- it records safe telemetry;
- it returns the same context.

## Error Handling

`execute` is allowed to throw `Exception`.

That is deliberate. Some nodes will perform network calls, parsing, model invocation or persistence, and those operations can fail. The node contract should not force every implementation to wrap all failures in a generic runtime exception.

The recommended pattern is:

- throw when the node cannot complete its responsibility;
- record safe context information when useful;
- do not swallow failures silently;
- do not write stack traces, raw payloads, prompts or secrets into the context;
- let the engine decide whether to retry, mark the workflow `PARTIAL`, mark it `FAILED`, branch to an error path or stop execution.

Example:

```java
try {
    return node.execute(context);
} catch (Exception ex) {
    context.error(node.id(), ex);
    node.onError(context, ex);
    throw ex;
}
```

The future engine can wrap this with timeout and retry behavior using `timeout()`, `maxRetries()` and `idempotent()`.

## Relationship with WorkflowContext

`WorkflowNode` and `WorkflowContext` are intentionally paired:

- `WorkflowNode` describes executable capability.
- `WorkflowContext` carries the data and execution trace.

The node should not introduce a second shared state object. It should not require a LangGraph4j state class, a Spring application context or a persistence session as part of its domain API.

If a concrete implementation needs services or clients, those dependencies should be supplied by the runtime adapter or by the application layer that instantiates the node. The domain contract remains:

```java
WorkflowContext execute(WorkflowContext context) throws Exception;
```

## Relationship With WorkflowAgent

`WorkflowAgent` represents reusable business logic. `WorkflowNode` represents a DAG step that can be scheduled by a workflow engine.

A node may delegate to an agent:

```text
MetadataWorkflowNode -> MetadataExtractionAgent
```

The node owns workflow concerns:

- named `WorkflowCapability` requirements and outputs;
- `canExecute` checks;
- timeout, retry, priority and idempotency metadata;
- scheduling and orchestration boundaries.

The agent owns reusable processing logic:

- type-level `requires()` and `produces()` declarations;
- document support checks;
- deterministic or AI-powered metadata;
- context enrichment.

This allows the same agent to be reused without a workflow node:

```text
REST Endpoint -> MetadataExtractionAgent
CLI Command   -> MetadataExtractionAgent
Batch Job     -> MetadataExtractionAgent
```

The agent still receives and returns `WorkflowContext`, but it does not know whether the caller is a node, endpoint, command or batch runner. See [Workflow agents](workflow-agents.md) for the dedicated contract guide.

## Current Implementation Status

Implemented:

- `WorkflowNode`
- `WorkflowNodeCategory`
- `WorkflowCapability`
- default `canExecute`
- default empty configuration
- lifecycle hooks
- default timeout, retry, parallelization, idempotency and priority policies
- unit tests for capability requirement checking, same-type capability disambiguation and default policies
- reusable workflow agent contracts in `it.osint.raven.workflow.agent`
- central workflow registry in `it.osint.raven.workflow.registry`

Not implemented yet:

- concrete production nodes;
- automatic node registration;
- DAG construction from `requires()` and `produces()`;
- LangGraph4j adapter;
- checkpoint persistence;
- workflow execution service.
