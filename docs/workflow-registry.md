# Workflow Registry

## Purpose

`WorkflowRegistry` is the central discovery registry for Raven workflow components.

It knows:

- `WorkflowNode`
- `WorkflowAgent`

It does not know:

- LangGraph4j;
- Spring;
- MongoDB, Neo4j or Qdrant;
- REST, CLI or batch runtimes.

The registry is the foundation for the future workflow compiler. A compiler will be able to inspect registered nodes, compare required and produced capabilities, and derive a valid execution plan without hard-coded node references.

## Package

```text
it.osint.raven.workflow.registry
```

Implemented types:

- `WorkflowRegistry`
- default in-memory implementation returned by `WorkflowRegistry.create()`

## API

```java
WorkflowRegistry registerNode(WorkflowNode node);
WorkflowRegistry registerAgent(WorkflowAgent agent);

Optional<WorkflowNode> findNode(String id);
Optional<WorkflowAgent> findAgent(String id);

List<WorkflowNode> findNodesProducing(WorkflowCapability capability);
List<WorkflowNode> findNodesRequiring(WorkflowCapability capability);

List<WorkflowNode> nodes();
List<WorkflowAgent> agents();
```

The registry preserves registration order and returns immutable snapshots from `nodes()` and `agents()`.

## Duplicate Handling

Node ids and agent ids are stable identifiers.

The registry rejects:

- two nodes with the same `WorkflowNode.id()`;
- two agents with the same `WorkflowAgent.id()`.

Duplicate registration throws `IllegalArgumentException`.

Node ids and agent ids are checked independently, so a node and an agent can share a similar business name when that is intentional. The future compiler should still prefer clear ids such as:

```text
metadata-node
metadata-agent
entity-extraction-node
entity-extraction-agent
```

## Capability Lookup

The registry can find producer and consumer nodes:

```java
List<WorkflowNode> producers =
        registry.findNodesProducing(METADATA);

List<WorkflowNode> consumers =
        registry.findNodesRequiring(STRUCTURED_DOCUMENT);
```

Capability matching delegates to `WorkflowCapability.matches(...)`.

That means matching is nominal:

- namespace must match;
- version must match;
- id or aliases may match;
- Java `Class<?> type` is ignored for dependency identity.

This keeps the future compiler focused on domain capabilities instead of Java implementation classes.

## ServiceLoader Discovery

The registry supports Java `ServiceLoader`, not Spring:

```java
WorkflowRegistry registry = WorkflowRegistry.load();
```

or with an explicit class loader:

```java
WorkflowRegistry registry = WorkflowRegistry.load(classLoader);
```

Provider modules can expose implementations through standard service files:

```text
META-INF/services/it.osint.raven.workflow.WorkflowNode
META-INF/services/it.osint.raven.workflow.agent.WorkflowAgent
```

Each file contains implementation class names, one per line.

No Spring component scanning is involved. Runtime adapters may choose to bridge Spring beans into a registry later, but that adapter belongs outside the workflow domain.

## Example

```java
WorkflowRegistry registry = WorkflowRegistry.create()
        .registerNode(metadataNode)
        .registerNode(entityExtractionNode)
        .registerAgent(metadataAgent);

WorkflowNode metadata = registry.findNode("metadata-node").orElseThrow();
WorkflowAgent agent = registry.findAgent("metadata-agent").orElseThrow();

List<WorkflowNode> entityProducers =
        registry.findNodesProducing(ENTITY_EXTRACTION);
```

## Current Implementation Status

Implemented:

- manual node registration;
- manual agent registration;
- duplicate id rejection;
- lookup by node id;
- lookup by agent id;
- producer lookup by `WorkflowCapability`;
- consumer lookup by `WorkflowCapability`;
- immutable node and agent snapshots;
- `ServiceLoader` discovery entry points;
- unit tests.

Not implemented yet:

- workflow compiler;
- automatic DAG construction;
- runtime execution service;
- LangGraph4j adapter;
- Spring bridge adapter.
