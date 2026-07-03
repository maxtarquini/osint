# Workflow Compiler

## Purpose

`WorkflowCompiler` is the heart of Raven's workflow architecture.

It transforms:

```text
WorkflowDefinition + WorkflowRegistry
```

into:

```text
ExecutionPlan
```

It does not use LangGraph4j.

It does not execute a graph.

It compiles a workflow request into a runtime-independent plan that a workflow engine can consume.

## Package

```text
it.osint.raven.workflow.compiler
```

Implemented types:

- `WorkflowCompiler`
- `ExecutionPlan`
- `ExecutionStage`
- `DependencyGraph`
- `DependencyEdge`
- `ExecutionOrder`
- `MissingCapabilityException`
- `AmbiguousCapabilityException`
- `CircularDependencyException`

## Architecture

The intended flow is:

```text
WorkflowDefinition (YAML)
  -> WorkflowCompiler
  -> ExecutionPlan
  -> WorkflowEngine
  -> WorkflowResult
```

Only a future LangGraph-specific engine adapter should know LangGraph4j. The compiler stays in Raven's domain layer.

## Algorithm

The compiler:

1. Reads workflow goals from `WorkflowDefinition`.
2. Finds registered nodes that produce each goal capability.
3. Resolves each selected node's required capabilities.
4. Adds missing dependency nodes automatically.
5. Builds a directed dependency graph.
6. Runs Kahn's topological sort algorithm.
7. Returns an `ExecutionPlan`.

Example:

```text
Goal: assessment

AssessmentNode
  requires claims

ClaimsNode
  requires entities

EntityNode
  requires structured-document

ParserNode
  produces structured-document
```

Compiled order:

```text
ParserNode
EntityNode
ClaimsNode
AssessmentNode
```

## ExecutionPlan

`ExecutionPlan` contains:

```text
WorkflowDefinition
ExecutionStage[]
DependencyGraph
ExecutionOrder
```

The plan is still engine-independent. It can be tested without LangGraph4j and can later be adapted to different runtimes.

## Capability Resolution

Capability lookup uses the registry:

```java
registry.findNodesProducing(capability);
```

Matching is based on `WorkflowCapability.matches(...)`, so the dependency identity is nominal:

- namespace;
- id or alias;
- version.

Java `Class<?> type` is validation metadata, not the dependency key.

## Errors

`MissingCapabilityException`

Raised when no registered node can produce a goal or dependency capability.

`AmbiguousCapabilityException`

Raised when more than one registered node can produce the same capability.

`CircularDependencyException`

Raised when the selected node graph contains a cycle. Cycle detection is based on the topological sort result.

## Current Implementation Status

Implemented:

- recursive dependency expansion from goals;
- automatic dependency node inclusion;
- dependency graph creation;
- Kahn topological sort;
- execution stages;
- execution order;
- missing capability error;
- ambiguous capability error;
- circular dependency error;
- unit tests for happy path, shared dependencies and error cases.

Not implemented yet:

- LangGraph4j adapter;
- checkpointing;
- parallel stage grouping;
- optional goal degradation policy.

See [Workflow engine](workflow-engine.md) for the execution contract and the current sequential reference implementation.
