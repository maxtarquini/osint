# REST API and OpenAPI

## Status

Raven currently exposes a small Spring Boot REST API for system information, external dependency configuration and connectivity probes.

The public API is documented with Springdoc OpenAPI:

- OpenAPI JSON: `GET /v3/api-docs`
- Swagger UI: `GET /swagger-ui.html`

The OpenAPI document is part of the build contract. Tests verify that the generated document contains the current endpoints and all public DTO schemas needed by API clients.

## Current Endpoints

### `GET /api/system/info`

Returns application name and version.

Response DTO:

- `AppInfo`

### `GET /api/system/configuration`

Returns the effective Raven external dependency configuration.

Response DTO:

- `RavenConfigurationDto`

### `PUT /api/system/configuration`

Persists Raven external dependency configuration and returns the normalized value.

Request DTO:

- `RavenConfigurationDto`

Response DTO:

- `RavenConfigurationDto`

Error DTO:

- `ApiErrorResponse`

### `GET /api/system/connections`

Runs TCP reachability probes for configured dependencies.

Response DTO:

- array of `ConnectionProbe`

## Documented Schemas

The OpenAPI components include schemas for current public DTOs and public enums used by the REST API or future generated clients:

- system DTOs: `AppInfo`, `ConnectionProbe`, `ConnectionState`, `ApiErrorResponse`, `EndpointConfigurationDto`, `QdrantConfigurationDto`, `RavenConfigurationDto`
- source DTOs: `SourceDto`, `SourceType`, `SourceStatus`, `AuthenticationDto`, `AuthenticationType`, `RawDocumentDto`
- article DTOs: `ArticleDto`, `MetadataDto`, `TaxonomyDto`, `EntityDto`, `EntityType`, `RelationshipDto`, `EventDto`, `IntelligenceAssessmentDto`, `AssessmentDto`, `EmbeddingDto`, `ProvenanceDto`, `LinksDto`, `ClaimDto`, `ClaimType`, `Confidence`, `EvidenceDto`, `EvidenceType`

Some DTOs are not yet returned by REST endpoints, but they are intentionally registered in OpenAPI components so external clients can be generated against a stable data contract as the API surface grows.

## Quality Gates

OpenAPI stability is enforced by tests under:

```text
src/test/java/it/osint/raven/openapi
```

The gates check:

- REST controllers under `/api/**` use `@Tag`;
- every endpoint mapping has `@Operation` and `@ApiResponses`;
- DTOs and public enums in the API contract declare `@Schema`;
- `/v3/api-docs` returns an OpenAPI 3 document;
- `/swagger-ui.html` is reachable;
- expected paths and component schemas are present.

When adding a new endpoint, update:

1. the controller Swagger annotations;
2. request and response DTO `@Schema` annotations;
3. `OpenApiConfiguration` if a DTO should be documented before it is directly referenced by an endpoint;
4. `OpenApiContractTest` and `OpenApiDocumentationQualityGateTest`.

## Python Client/TUI Readiness

The OpenAPI document is the intended source for generated clients, including a future Python textual interface.

Recommended direction:

```text
Spring Boot REST API
  -> /v3/api-docs
  -> generated Python client
  -> Textual TUI application
```

The Python TUI should be a separate client package, not embedded into the Spring Boot application.
