# User Guide

## Purpose

Raven is a terminal application for OSINT workflows. It is designed to help operators configure external infrastructure, monitor connectivity and eventually run acquisition and analysis pipelines from a keyboard-first interface.

At the current stage, Raven provides:

- a full-screen terminal workspace;
- connection status probes for Neo4j, Qdrant and MongoDB;
- configuration editing for dependency endpoints and UI preferences;
- foundational data models and Mongo repositories for OSINT sources, raw documents and articles.

## Start Raven

Build and run the application:

```bash
mvn -q -DskipTests package
java -jar target/raven-0.1.0-SNAPSHOT.jar
```

The main class is `it.osint.raven.RavenApplication`.

## Main Screen

The main screen contains:

- top bar with `Refresh`, `Config` and `Exit`;
- connection indicators for Neo4j, Qdrant HTTP, Qdrant gRPC and MongoDB;
- sidebar placeholders for Dashboard, Graph, Agents, Config and Logs;
- dashboard summary of enabled modules;
- footer with current configuration path and UI density.

## Configure Dependencies

Open `Config` from the top bar or sidebar.

The configuration dialog allows editing:

- Neo4j host and port;
- Qdrant host, HTTP port and gRPC port;
- MongoDB host and port;
- status colors;
- mouse input;
- UI density.

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

Use `Refresh` to rerun probes after starting or changing dependencies.

## Current Limitations

The TUI does not yet expose source CRUD, acquisition execution, parsing, LLM analysis or knowledge graph exploration. Those workflows are documented as the target direction and are backed by the initial DTO and repository layers.
