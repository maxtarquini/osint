# Raven OSINT REST API

Raven is a Spring Boot REST API for OSINT acquisition, document processing, graph analysis, vector search and agent workflows.

Current implementation focuses on:

- REST bootstrap with Spring Boot 4;
- typed configuration for Neo4j, Qdrant and MongoDB;
- connection probes for external dependencies;
- DTO model for OSINT sources, raw documents and intelligence articles;
- engine-independent workflow context, node contract, reusable agent contract and sequential workflow engine;
- Spring Data MongoDB repositories for sources, raw documents and articles;
- OpenAPI 3 documentation through Springdoc, including DTO schemas and Swagger UI.

## Documentation

- [Documentation index](docs/README.md)
- [User guide](docs/user-guide.md)
- [REST API and OpenAPI](docs/api-reference.md)
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

The test suite includes OpenAPI quality gates that verify:

- every REST controller under `/api/**` is tagged;
- every mapped endpoint has `@Operation` and `@ApiResponses`;
- every documented DTO and public enum has Swagger schema metadata;
- `/v3/api-docs` and Swagger UI are served by the running Spring Boot application.

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

OpenAPI endpoints:

- `GET /v3/api-docs`
- `GET /swagger-ui.html`

## Interface Strategy

The Java application is backend-only. The previous Java terminal UI has been removed. Any future textual interface should be implemented as a separate Python client, preferably with Textual, consuming the Spring Boot REST API and generated from `/v3/api-docs` where practical.
