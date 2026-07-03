# Workflow Engine

## Purpose

`WorkflowEngine` is Raven's engine-independent execution contract for compiled workflows.

It consumes:

```text
ExecutionPlan + WorkflowContext
```

and returns:

```text
WorkflowResult
```

The engine layer does not compile workflows. It does not build a dependency graph, resolve capabilities, choose nodes or create a DAG. Those responsibilities belong to `WorkflowCompiler`.

The current reference implementation is `SequentialWorkflowEngine`.

## Package

```text
it.osint.raven.workflow.engine
```

Implemented types:

- `WorkflowEngine`
- `SequentialWorkflowEngine`
- `WorkflowResult`
- `WorkflowExecutionStatus`

## Architecture

The implemented flow is:

```text
WorkflowDefinition
  -> WorkflowCompiler
  -> ExecutionPlan
  -> WorkflowEngine
  -> WorkflowResult
```

LangGraph4j is intentionally not part of this contract. A future `LangGraphWorkflowEngine` can implement the same interface and produce equivalent results through LangGraph4j, but LangGraph4j remains an adapter/runtime detail.

## Contract

```java
WorkflowResult execute(
        ExecutionPlan plan,
        WorkflowContext context)
        throws Exception;
```

The supplied context is the shared state passed through every node:

```java
WorkflowEngine engine = new SequentialWorkflowEngine();
WorkflowResult result = engine.execute(plan, context);
```

Nodes are executed with the simple domain rule:

```java
context = node.execute(context);
```

This means nodes may mutate and return the same context, or return a replacement `WorkflowContext`. The engine continues with the returned context.

## SequentialWorkflowEngine

`SequentialWorkflowEngine` executes nodes in `ExecutionPlan.executionOrder()`.

For each node, it:

1. Verifies runtime requirements with `node.canExecute(context)`.
2. Emits a `NODE_STARTED` event through `WorkflowContext.event`.
3. Calls `node.beforeExecute(context)`.
4. Calls `node.execute(context)`.
5. Calls `node.afterExecute(context)` after successful execution.
6. Measures node duration and stores a metric.
7. Emits a `NODE_COMPLETED` event after success.
8. Calls `node.onError(context, ex)` on failure.
9. Records structured failures with `WorkflowContext.error`.
10. Applies retry policy when allowed.

It does not use logger APIs. Runtime trace information is recorded only through `WorkflowContext` events, warnings, errors and metrics.

## Retry Policy

Retry behavior is controlled by node metadata:

```java
node.maxRetries();
node.idempotent();
```

Rules:

- idempotent nodes can be retried up to `maxRetries`;
- non-idempotent nodes are executed only once;
- negative retry values are treated as zero retries;
- every failed attempt records an error and `NODE_FAILED` event.

This keeps side-effecting nodes safe by default when they declare `idempotent() == false`.

## Timeout Policy

`SequentialWorkflowEngine` reads:

```java
node.timeout();
```

The current implementation measures elapsed time around the synchronous node call. If the call completes after the declared timeout, the attempt is treated as failed with a `TimeoutException`.

It deliberately does not start worker threads, thread pools or `CompletableFuture` tasks. This preserves the current sequential reference behavior and keeps hard cancellation for a later runtime implementation.

## Result Model

`WorkflowResult` contains:

- `ExecutionPlan plan`;
- `WorkflowContext context`;
- `WorkflowExecutionStatus status`;
- `Instant startedAt`;
- `Instant completedAt`;
- `Duration duration`;
- executed node ids;
- failed node ids;
- skipped node ids;
- final metrics snapshot.

`WorkflowExecutionStatus` values:

- `SUCCESS`;
- `PARTIAL_SUCCESS`;
- `FAILED`;
- `CANCELLED`.

The engine also maps the terminal execution status back into `WorkflowContext.status`:

- `SUCCESS` -> `COMPLETED`;
- `PARTIAL_SUCCESS` -> `PARTIAL`;
- `FAILED` -> `FAILED`;
- `CANCELLED` -> `FAILED`.

## Skipped Nodes

A node is skipped when `node.canExecute(context)` returns `false`.

This is a runtime guard. The compiler is still responsible for building a valid plan from declared capabilities, but a context may still be missing starting artifacts or outputs from failed upstream work.

Skipped node ids are reported in `WorkflowResult.skippedNodes()` and a warning is recorded in the context.

## Current Implementation Status

Implemented:

- engine interface;
- immutable result model;
- terminal execution status enum;
- sequential reference engine;
- lifecycle hooks;
- retry policy;
- measured timeout policy;
- skipped node reporting;
- context event/error/warning/metric based observability;
- unit tests for successful execution, lifecycle order, retry, non-idempotent failure, missing requirements, timeout and returned-context replacement.

Not implemented yet:

- LangGraph4j engine adapter;
- hard timeout cancellation;
- thread pools;
- parallel execution;
- checkpointing;
- branch or degradation policies beyond skipped/failed node reporting.
