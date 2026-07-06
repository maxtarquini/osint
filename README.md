# Raven OSINT REST API

Raven is a Spring Boot REST API for OSINT acquisition, document processing, graph analysis, vector search and agent workflows.

Current implementation focuses on:

- REST bootstrap with Spring Boot 4;
- typed configuration for Neo4j, Qdrant and MongoDB;
- connection probes for external dependencies;
- DTO model for OSINT sources, raw documents and intelligence articles;
- engine-independent workflow context, node contract, reusable agent contract and sequential workflow engine;
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
- [Workflow compiler](docs/workflow-compiler.md)
- [Workflow engine](docs/workflow-engine.md)
- [Data flows](docs/data-flows.md)
- [Model reference](docs/model-reference.md)

## Build

```bash
mvn test
```

## Run

```bash
mvn spring-boot:run
```

The application listens on `http://localhost:8080` and reads/writes its local configuration at `config/raven.yaml`.

Initial REST endpoints:

- `GET /api/system/info`
- `GET /api/system/configuration`
- `PUT /api/system/configuration`
- `GET /api/system/connections`
