# Workflow Agents

## Purpose

`WorkflowAgent` is the Raven domain contract for reusable business logic.

An agent receives a `WorkflowContext`, reads the inputs it needs, produces new artifacts or observations, and returns the enriched context:

```java
WorkflowContext execute(WorkflowContext context) throws Exception;
```

The important distinction is that an agent is not a workflow node.

- `WorkflowAgent` represents reusable business capability.
- `WorkflowNode` represents an executable step inside a workflow DAG.
- LangGraph4j, REST endpoints, CLI commands and batch jobs are runtime entry points that may call the same agent.

This lets Raven reuse the same implementation in different contexts:

```text
MetadataWorkflowNode -> MetadataExtractionAgent
REST Endpoint       -> MetadataExtractionAgent
CLI Command         -> MetadataExtractionAgent
Batch Job           -> MetadataExtractionAgent
```

The agent does not know which caller invoked it.

Agents can be registered in `WorkflowRegistry` alongside nodes. The registry provides id lookup and future compiler discovery without making agents depend on a workflow engine.

## Package

```text
it.osint.raven.workflow.agent
```

Implemented contracts:

- `WorkflowAgent`
- `WorkflowAgentType`
- `DeterministicAgent`
- `LlmAgent`
- `ConnectorAgent`

## Runtime Independence

Workflow agents are part of the engine-independent workflow domain. They must not depend on:

- LangGraph4j;
- LangChain4j;
- OpenAI clients;
- Spring annotations or dependency injection;
- MongoDB, Neo4j, Qdrant or other persistence clients;
- REST controllers or CLI frameworks;
- prompt template implementations.

An adapter can wrap an agent and supply infrastructure elsewhere. The agent contract itself only knows `WorkflowContext` and `StructuredDocument`.

## Contract

Every agent declares stable metadata:

```java
String id();
String name();
String description();
WorkflowAgentType type();
```

`id()` must be stable across releases because it can appear in artifact provenance, events, traces and future workflow definitions:

```java
metadata-agent
entity-extraction-agent
pdf-parser-agent
```

Every agent also declares type-level capabilities:

```java
Set<Class<?>> requires();
Set<Class<?>> produces();
```

These are intentionally simpler than `WorkflowNode` capabilities. They describe business-level inputs and outputs that can be used by workflow nodes, REST endpoints, CLI commands or discovery tools. A `WorkflowNode` can translate these declarations into named `WorkflowCapability` values when building a DAG.

Example:

```java
@Override
public Set<Class<?>> requires() {
    return Set.of(StructuredDocument.class);
}

@Override
public Set<Class<?>> produces() {
    return Set.of(MetadataDto.class);
}
```

## Document Support

Agents can declare whether they support a structured document:

```java
boolean supports(StructuredDocument document);
```

Examples:

- `MetadataExtractionAgent` may support `ArticleDto` and future `PDFDocumentDto`.
- `ImageCaptionAgent` may support only a future `ImageDocumentDto`.
- connector or context-only utility agents may ignore the document.

The default implementation returns `true`.

## Agent Types

`WorkflowAgentType` has these values:

```text
CONNECTOR
PARSER
ENRICHMENT
CLASSIFICATION
EXTRACTION
REASONING
EMBEDDING
PERSISTENCE
EXPORT
VALIDATION
UTILITY
```

The type describes the business capability, not the workflow node category and not the runtime implementation.

## Specializations

Raven defines lightweight specializations for future extension:

```text
WorkflowAgent
  ├─ DeterministicAgent
  ├─ LlmAgent
  └─ ConnectorAgent
```

`DeterministicAgent` is for traditional algorithms such as parsers, normalizers, validators and deduplicators. It defaults to:

```java
aiPowered() == false
deterministic() == true
```

`LlmAgent` is for language-model-backed agents. It defaults to:

```java
aiPowered() == true
deterministic() == false
```

`ConnectorAgent` is for agents that acquire data from external sources. It defaults to:

```java
type() == WorkflowAgentType.CONNECTOR
```

These interfaces do not introduce model clients, prompt objects or connector clients. They only make intent explicit while keeping the common `WorkflowAgent` contract.

## AI Metadata

The base contract includes AI-related metadata without implementing any AI runtime:

```java
default boolean aiPowered()
default boolean deterministic()
default Optional<String> modelName()
default Optional<String> promptId()
```

Deterministic agents normally return:

```java
aiPowered() == false
deterministic() == true
modelName() == Optional.empty()
promptId() == Optional.empty()
```

LLM agents normally return:

```java
aiPowered() == true
deterministic() == false
modelName() == Optional.of("gpt-5")
promptId() == Optional.of("registered-prompt-id")
```

`promptId()` is only a future reference to a registered prompt. Prompt templates are not part of the current contract.

## Configuration

Agents can expose safe, non-secret configuration metadata:

```java
default Map<String, Object> configuration()
```

The default is an empty map. Do not expose passwords, tokens, raw documents, prompt bodies, model payloads, clients or repositories through this method.

## Lifecycle Hooks

Agents can optionally expose lifecycle hooks:

```java
default void beforeExecute(WorkflowContext context)
default void afterExecute(WorkflowContext context)
default void onError(WorkflowContext context, Exception ex)
```

The hooks are no-ops by default. Runtime adapters, workflow nodes or application callers can decide when to call them. The hooks should not assume a specific engine.

## Metrics And Events

Agents do not use loggers directly. They record observations in `WorkflowContext`:

```java
context.metric("metadata_fields_extracted", 5);
context.event(id(), WorkflowEventType.NODE_COMPLETED, "Metadata extraction completed");
context.warning("Metadata extraction completed with missing author");
context.error(id(), ex);
```

Metrics use `context.metric(...)`; there is no dedicated agent metrics API.

Do not record raw document content, credentials, prompts, full LLM payloads, secrets or stack traces in context events, warnings, variables or metrics.

## Relationship With WorkflowNode

A workflow node can wrap an agent:

```java
public final class MetadataWorkflowNode implements WorkflowNode {

    private final WorkflowAgent agent;

    public MetadataWorkflowNode(WorkflowAgent agent) {
        this.agent = agent;
    }

    @Override
    public WorkflowContext execute(WorkflowContext context) throws Exception {
        agent.beforeExecute(context);
        try {
            WorkflowContext result = agent.execute(context);
            agent.afterExecute(result);
            return result;
        } catch (Exception ex) {
            agent.onError(context, ex);
            throw ex;
        }
    }
}
```

The node owns DAG-level concerns such as named `WorkflowCapability` requirements, retry policy, timeout, priority and scheduling metadata. The agent owns the reusable business logic.

## Direct Usage

The same agent can be used without a workflow node:

```java
WorkflowAgent agent = new MetadataExtractionAgent();

WorkflowContext context = new WorkflowContext()
        .document(article)
        .put("parser", article);

context = agent.execute(context);
```

This is the design goal: agents can be reused by workflow nodes, REST endpoints, CLI commands, batch jobs or tests without depending on the workflow engine.

## Current Implementation Status

Implemented:

- `WorkflowAgent`
- `WorkflowAgentType`
- `DeterministicAgent`
- `LlmAgent`
- `ConnectorAgent`
- unit tests for defaults, metadata and direct execution

Not implemented yet:

- concrete production agents;
- prompt templates;
- model clients;
- LangChain4j or OpenAI integration;
- LangGraph4j adapters;
- REST, CLI or batch adapters;
- automatic agent discovery or registration.
