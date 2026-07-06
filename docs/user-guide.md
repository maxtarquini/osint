# User Guide

## Purpose

Raven is a Spring Boot REST application for OSINT workflows. It is designed to help operators configure external infrastructure, monitor connectivity and eventually run acquisition and analysis pipelines through HTTP endpoints.

At the current stage, Raven provides:

- REST endpoints under `/api/system`;
- OpenAPI JSON and Swagger UI;
- connection status probes for Neo4j, Qdrant and MongoDB;
- configuration read/update for dependency endpoints;
- foundational data models and Spring Data MongoDB repositories for OSINT sources, raw documents and articles;
- an internal workflow context model and node contract for future parser, workflow node and AI agent execution.

## Start Raven

Build and run the application:

```bash
mvn spring-boot:run
```

The main class is `it.osint.raven.RavenApplication`.
The default local URL is:

```text
http://localhost:8080
```

You can also package and run the executable jar:

```bash
mvn -q -DskipTests package
java -jar target/raven-0.1.0-SNAPSHOT.jar
```

## REST Endpoints

The initial API surface is:

- `GET /api/system/info`
- `GET /api/system/configuration`
- `PUT /api/system/configuration`
- `GET /api/system/connections`

Interactive API documentation is available at:

```text
http://localhost:8080/swagger-ui.html
```

The raw OpenAPI document is available at:

```text
http://localhost:8080/v3/api-docs
```

These endpoints are useful for manual testing and for generating future clients, including a Python textual interface.

## Configure Dependencies

Use `GET /api/system/configuration` to read the effective configuration and `PUT /api/system/configuration` to save changes. You can call these endpoints from Swagger UI, curl, a generated client or any HTTP tool.

The configuration payload allows editing:

- Neo4j host and port;
- Qdrant host, HTTP port and gRPC port;
- MongoDB host and port;

When saved, Raven writes normalized configuration to:

```text
config/raven.yaml
```

Default endpoints:

```yaml
neo4j:
  host: localhost
  port: 7687
qdrant:
  host: localhost
  httpPort: 6333
  grpcPort: 6334
mongodb:
  host: localhost
  port: 27017
```

## Connection Status

Raven shows each dependency as:

- `online`: TCP connection succeeded;
- `offline`: TCP connection failed;
- `invalid`: host or port is not valid.

Call `GET /api/system/connections` to rerun probes after starting or changing dependencies.

Example response shape:

```json
[
  {
    "name": "MongoDB",
    "host": "localhost",
    "port": 27017,
    "state": "ONLINE"
  }
]
```

## Textual Interface

The current Java application does not include a TUI or graphical frontend. The previous Java terminal UI has been removed.

The recommended future interface is a separate Python Textual client that consumes Raven through HTTP and uses `/v3/api-docs` to generate or validate its API client layer.

## Current Limitations

The REST API does not yet expose source CRUD, acquisition execution, parsing, LLM analysis, workflow execution or knowledge graph exploration. Those workflows are documented as the target direction and are backed by the initial DTO, Spring Data repository, workflow context, compiler and workflow engine layers.

`WorkflowContext` and `WorkflowNode` are currently internal developer-facing models. They are not yet exposed as public REST resources and do not yet imply that Raven has a complete production workflow API. The contract for nodes exists so future connectors, parsers, AI extractors and persistence steps can be built consistently before the orchestration layer is introduced.
