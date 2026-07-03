# Raven Documentation

This folder contains the first documentation set for Raven.

The documentation is organized by audience and use case:

- [User guide](user-guide.md): how to launch Raven, configure dependencies and understand the current TUI.
- [Technical architecture](technical-architecture.md): package structure, persistence, DTO boundaries and current technology choices.
- [Workflow guide](workflows.md): operational workflows for source management, acquisition and parsing.
- [Workflow context](workflow-context.md): shared execution state used by workflow nodes and workflow agents.
- [Workflow nodes](workflow-nodes.md): engine-independent node contract, categories, capability declarations and runtime policy metadata.
- [Workflow agents](workflow-agents.md): reusable business-logic contract used by workflow nodes, REST endpoints, CLI commands and batch jobs.
- [Workflow registry](workflow-registry.md): central node and agent registry used for id lookup, capability lookup and future workflow compilation.
- [Workflow definitions](workflow-definitions.md): workflow-level goal definitions loaded from YAML without describing a DAG.
- [Workflow compiler](workflow-compiler.md): runtime-independent compiler from workflow definitions to execution plans.
- [Workflow engine](workflow-engine.md): engine contract, sequential reference implementation and execution result model.
- [Data flows](data-flows.md): end-to-end flows from Source to Knowledge Graph.
- [Model reference](model-reference.md): current DTOs, repository collections and JSON contract.

## Documentation Status

Raven is still in an early platform stage. Some documents describe implemented behavior, while others define the target architecture that the code is being shaped toward.

Each section marks future capabilities explicitly as `Planned`.
