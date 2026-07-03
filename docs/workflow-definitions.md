# Workflow Definitions

## Purpose

`WorkflowDefinition` describes a Raven workflow.

It does not describe a DAG.

A definition answers:

- what workflow is being requested;
- which goals should be achieved;
- which safe configuration and metadata apply.

It does not answer:

- which nodes will run;
- in what order nodes will run;
- which graph engine will execute the workflow;
- how LangGraph4j should be wired.

The future compiler will combine:

- `WorkflowDefinition`;
- `WorkflowRegistry`;
- registered `WorkflowNode` capabilities;
- registered `WorkflowAgent` metadata.

Only then will Raven build a concrete DAG or runtime plan.

## Package

```text
it.osint.raven.workflow.definition
```

Implemented types:

- `WorkflowDefinition`
- `WorkflowGoal`

## WorkflowDefinition

Fields:

```text
id
name
description
version
goals
configuration
metadata
```

`id` and `version` are required.

`goals` is an ordered list of desired outcomes. Each goal contains a `WorkflowCapability`, but it does not name a node.

`configuration` and `metadata` are safe maps for workflow-level options and descriptive information. They must not contain credentials, raw documents, prompts or model payloads.

## WorkflowGoal

Fields:

```text
capability
required
priority
```

Examples of goal capability ids:

```text
metadata
entities
claims
assessment
neo4j
```

The goal says "this workflow should produce metadata" or "this workflow should produce entities". The compiler later decides which registered node or chain of nodes can satisfy that goal.

## YAML

Raven uses SnakeYAML for load and save support.

Minimal YAML:

```yaml
workflow:
  id: libya-observer
  version: 1.0

goals:
  - metadata
  - entities
  - claims
  - assessment
```

This format does not describe nodes. It describes only objectives.

Extended goal syntax is also supported for future compiler hints:

```yaml
workflow:
  id: graph-export
  name: Graph Export
  description: Export enriched article to graph
  version: 2.1.0

configuration:
  dry_run: true

metadata:
  owner: osint-team

goals:
  - id: neo4j
    namespace: graph
    description: Persist graph projection
    version: 1.2.0
    required: false
    priority: 50
```

## API

```java
WorkflowDefinition definition = WorkflowDefinition.load(path);
WorkflowDefinition definition = WorkflowDefinition.load(yamlText);

definition.validate();
definition.save(path);

String yaml = definition.toYaml();
```

Validation checks:

- workflow id is present;
- workflow version is present and parseable;
- goals are not null;
- goal capabilities are valid;
- duplicate goal capabilities are rejected.

Validation does not check node availability and does not build a DAG. Those responsibilities belong to the future compiler.

## Current Implementation Status

Implemented:

- immutable `WorkflowDefinition`;
- immutable `WorkflowGoal`;
- YAML load with SnakeYAML;
- YAML save with SnakeYAML;
- simple goal list syntax;
- extended goal map syntax;
- validation for id, version, null goals and duplicate goals;
- unit tests.

Not implemented yet:

- workflow compiler;
- DAG construction;
- node selection;
- registry satisfaction checks;
- LangGraph4j adapter.
