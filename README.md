# Raven OSINT

Raven is a Java terminal workspace for OSINT acquisition, document processing, graph analysis, vector search and agent workflows.

Current implementation focuses on:

- terminal UI bootstrap with Lanterna;
- typed configuration for Neo4j, Qdrant and MongoDB;
- connection probes for external dependencies;
- DTO model for OSINT sources, raw documents and intelligence articles;
- engine-independent workflow context, node contract and reusable agent contract for future workflow and agent execution;
- MongoDB repositories for sources, raw documents and articles.

## Documentation

- [Documentation index](docs/README.md)
- [User guide](docs/user-guide.md)
- [Technical architecture](docs/technical-architecture.md)
- [Workflow guide](docs/workflows.md)
- [Workflow context](docs/workflow-context.md)
- [Workflow nodes](docs/workflow-nodes.md)
- [Workflow agents](docs/workflow-agents.md)
- [Workflow registry](docs/workflow-registry.md)
- [Workflow definitions](docs/workflow-definitions.md)
- [Data flows](docs/data-flows.md)
- [Model reference](docs/model-reference.md)

## Build

```bash
mvn test
```

## Run

```bash
mvn -q -DskipTests package
java -jar target/raven-0.1.0-SNAPSHOT.jar
```

The application reads and writes its local configuration at `config/raven.yaml`.
