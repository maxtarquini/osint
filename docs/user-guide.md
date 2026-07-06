# User Guide

## Purpose

Raven is a Spring Boot REST application for OSINT workflows. It is designed to help operators configure external infrastructure, monitor connectivity and eventually run acquisition and analysis pipelines through HTTP endpoints.

At the current stage, Raven provides:

- REST endpoints under `/api/system`;
- connection status probes for Neo4j, Qdrant and MongoDB;
- configuration read/update for dependency endpoints;
- foundational data models and Mongo repositories for OSINT sources, raw documents and articles;
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

## Configure Dependencies

Use `GET /api/system/configuration` to read the effective configuration and `PUT /api/system/configuration` to save changes.

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

## Current Limitations

The REST API does not yet expose source CRUD, acquisition execution, parsing, LLM analysis, workflow execution or knowledge graph exploration. Those workflows are documented as the target direction and are backed by the initial DTO, repository, workflow context and workflow node contract layers.

`WorkflowContext` and `WorkflowNode` are currently internal developer-facing models. They are not yet exposed as public REST resources and do not yet imply that Raven has a complete production workflow API. The contract for nodes exists so future connectors, parsers, AI extractors and persistence steps can be built consistently before the orchestration layer is introduced.
