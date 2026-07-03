# Backend Java Development Guidelines

This document defines the recommended backend development standards for the Atlas Java codebase.
It is based on the current Spring Boot architecture and should be used as a reference when introducing new backend features.

For standalone Java terminal applications, also review `dev-guides/TUI_DEVELOPMENT_GUIDELINES.md`. Spring-specific package names such as `com.velia.components` and `com.velia.services` apply only to Spring modules; standalone TUI projects should preserve the same separation of concerns using their own base package and TUI/service/repository/graph layers.

Raven-specific note: the `it.osint.raven.workflow` package contains engine-independent workflow domain state, node contracts and reusable agent contracts. Classes in this package must not depend on Spring, LangGraph4j, LangChain4j, OpenAI clients, MongoDB, Neo4j, Qdrant or concrete serialization frameworks.

## 1) Package organization

Use package-by-layer with domain sub-packages where needed.

### 1.1 Base package
- Root package: `com.velia`

### 1.2 Main layer packages
- `controllers` → REST API endpoints.
- `services` → business logic orchestration and integrations.
- `components` → processing blocks, mappers, enrichers, domain processors.
- `repositories` → Spring Data repositories and persistence access.
- `dto` → API/persistence transfer models.
- `config` → Spring configuration.
- `controlleradvices` → exception mapping and cross-cutting HTTP error handling.
- `exceptions` → domain/application exceptions.
- `queues` → queue abstractions and queue wiring.
- `utils` → stateless utility helpers/constants.
- `agents` → AI agents organized by phase/domain.
- `workflow` → engine-independent workflow execution state, events, artifacts and status models.

### 1.3 Domain-oriented sub-packages
When a layer becomes large, split by domain:
- `dto/sigint`, `dto/spotrep`, `dto/tadf`, `dto/windowing`, etc.
- `services/windowing`, `services/rag`, `services/system`.
- `components/phase1`, `components/phase2`, `components/fieldunits`, `components/heatmaps/eventbased`.
- `utils/notifications`, `utils/kb`, `utils/tenantdashboard`, `utils/<domain>`.
- `agents/phase1/*`, `agents/phase2/*`.

### 1.4 Packaging rules
- Put classes in the package matching their primary responsibility.
- Avoid "misc"/catch-all packages for production code.
- Keep naming predictable and aligned with current conventions (`*Controller`, `*Service`, `*Repository`, `*Dto`, `*Processor`, `*Agent`, `*Assistant`).
- Reusable Spring-managed processing classes belong under `com.velia.components.<domain>`, never directly under services, utils, root packages or unrelated feature packages.
- Stateless utility/helper classes belong under `com.velia.utils.<domain>` or a stable existing `utils` sub-package; avoid adding new utility classes directly under `com.velia.utils` when a domain sub-package exists or can be created.

### 1.5 Mandatory package for agent classes
- All agent classes (`*Agent`, `*Assistant`, related agent prompt loaders) must be placed under `com.velia.agents`.
- Agents must be organized in thematic sub-packages (examples: `com.velia.agents.edt`, `com.velia.agents.phase1`, `com.velia.agents.classification`, `com.velia.agents.<domain>`).
- Avoid placing agent classes under unrelated packages (`services`, `components`, `utils`) when they represent AI agent execution units.
- Raven exception: engine-independent workflow agent contracts live under `it.osint.raven.workflow.agent`. These are domain contracts, not Spring-managed AI execution units, and must stay free from framework imports. Concrete application agents or adapters that use Spring, model clients, queues or prompt loaders belong outside the workflow domain.

---

## 2) DTO development standards

### 2.1 DTO purpose
Use DTOs for:
- API request/response payloads.
- persistence records (Mongo `@Document` where applicable).
- inter-layer transfer models between services/components.

### 2.2 DTO structure
Current codebase standard (recommended by default):
- Lombok for boilerplate reduction (`@Data`, `@Builder`, `@NoArgsConstructor`, `@AllArgsConstructor`, optional `@With`, `@ToString`).
- Jackson annotations where needed (`@JsonProperty`, `@JsonInclude`, `@JsonIgnoreProperties`).
- Spring Data annotations for persisted DTOs (`@Document`, `@Id`, `@Indexed`, `@CompoundIndex`).
- Explicit domain defaults via `@Builder.Default` for deterministic behavior.

### 2.3 DTO package placement
- Place DTOs in domain-specific sub-package under `dto`.
- Place shared cross-domain DTOs in `dto/commons`.
- Keep nested object DTOs in same domain package unless reused by multiple domains.
- Do not use nested classes

### 2.4 DTO design rules
- Keep DTOs focused on data representation, not business logic.
- Prefer immutable update patterns (`withX(...)`) where already used.
- Document all externally exposed fields with Swagger `@Schema`.
- For persistence DTOs, define indexes intentionally and name them explicitly.

### 2.5 DTO compliance checklist (mandatory for API/persistence DTOs)
- Add class-level `@Schema(description = "...")`.
- Add field-level `@Schema` for externally exposed properties.
- Use `@JsonIgnoreProperties(ignoreUnknown = true)` for resilient deserialization where appropriate.
- Prefer Lombok consistency (`@Builder`, `@With`, `@EqualsAndHashCode`, `@ToString`, getters/setters) unless Java `record` is intentionally chosen.
- If using Java `record`, annotate record components with `@Schema`.

---

## 2.6 Raven workflow domain standards

These rules apply to `it.osint.raven.workflow` and its sub-packages.

`WorkflowContext` is the only shared state object passed between workflow nodes and workflow agents. It is not a persistence DTO, not a Spring component and not a LangGraph4j state subclass.

`WorkflowNode` is the engine-independent contract for executable workflow steps. It is also a domain contract, not a Spring bean contract and not a LangGraph4j node action.

`WorkflowAgent` is the engine-independent contract for reusable business logic that can be called by workflow nodes, REST endpoints, CLI commands or batch jobs. It is not a workflow node, not a Spring service and not a LangChain4j assistant.

`WorkflowRegistry` is the engine-independent registry for workflow nodes and workflow agents. It supports manual registration and Java `ServiceLoader`; it must not use Spring component scanning.

`WorkflowDefinition` is the engine-independent workflow description. It declares workflow metadata and goals, not nodes and not a DAG.

Implementation rules:

- Keep workflow model classes independent from Spring annotations and dependency injection.
- Keep workflow model classes independent from LangGraph4j APIs.
- Keep workflow model classes independent from LangChain4j, OpenAI clients and prompt template implementations.
- Keep workflow model classes independent from MongoDB, Neo4j and Qdrant driver types.
- Keep `WorkflowNode` implementations that live in the workflow package free from framework imports. Runtime adapters may wrap them elsewhere.
- Keep `WorkflowAgent` implementations that live in the workflow package free from framework imports. Runtime adapters, application services or concrete external-source clients may wrap them elsewhere.
- Keep `WorkflowRegistry` independent from Spring and LangGraph4j. Service discovery in the workflow domain must use Java `ServiceLoader`; Spring bridges belong outside the domain.
- Keep `WorkflowDefinition` independent from graph runtimes. Definitions describe goals only; DAG construction belongs to a later compiler.
- Use Java 21 standard library types for timestamps, identifiers, maps and lists.
- Use `ConcurrentHashMap` for concurrently updated maps.
- Use thread-safe lists where concurrent node execution can append observations.
- Prefer small records for immutable value objects such as events, errors and artifacts.
- Keep `WorkflowError` serializable and safe: store exception class names or codes, not `Throwable` instances or stack traces.
- Do not store database clients, service instances, model clients, prompt objects or framework state inside `WorkflowContext`.

Workflow node contract rules:

- Every executable node must implement `WorkflowNode`.
- Every node must define a stable `id`, readable `name`, short `description`, and `WorkflowNodeCategory`.
- Every node must declare mandatory upstream capabilities through `requires`.
- Every node must declare produced capabilities through `produces`.
- Use `WorkflowCapability` as a domain value object identified by namespace, id and version; `Class<?> type` is only for validation and must not define DAG dependencies.
- `canExecute` should remain based on `WorkflowContext.contains(WorkflowCapability)`; do not replace it with reflection or framework metadata inspection.
- Use `configuration` only for safe node metadata/configuration. Do not expose passwords, tokens, prompts, raw documents, clients or repositories.
- Override `timeout`, `maxRetries`, `parallelizable`, `idempotent`, and `priority` whenever the defaults would misrepresent runtime behavior.
- Non-idempotent persistence, webhook or external side-effect nodes must explicitly return `false` from `idempotent` unless they implement stable deduplication/upsert semantics.
- Nodes may throw checked exceptions from `execute`; engines/adapters decide retry, branch, partial failure or terminal failure behavior.

Workflow agent contract rules:

- Every reusable domain agent must implement `WorkflowAgent` or one of its specializations.
- Every agent must define a stable `id`, readable `name`, short `description`, and `WorkflowAgentType`.
- Every agent must declare type-level inputs through `Set<Class<?>> requires()`.
- Every agent must declare type-level outputs through `Set<Class<?>> produces()`.
- Use `supports(StructuredDocument)` to restrict an agent to concrete document DTOs when needed.
- Use `configuration` only for safe agent metadata/configuration. Do not expose passwords, tokens, prompts, raw documents, clients or repositories.
- Deterministic algorithms should implement `DeterministicAgent`.
- LLM-backed agents should implement `LlmAgent`, return `aiPowered() == true`, normally return `deterministic() == false`, and may expose `modelName()` and `promptId()`.
- Connector-style agents should implement `ConnectorAgent` when they acquire data from external sources.
- Agents may throw checked exceptions from `execute`; callers decide retry, branch, partial failure or terminal failure behavior.
- Agents must not use loggers directly when they live in the workflow domain; record events, warnings, errors and metrics in `WorkflowContext`.

Shared output rules:

- Do not add a field to `WorkflowContext` for every new agent result.
- Store node outputs through capability-aware `put`, backed by named capability artifacts.
- Use `producedBy` whenever the producer node or agent is known.
- Use `get` for optional inputs.
- Use `require` for mandatory upstream inputs.
- Remember that `canExecute` checks named capability artifacts through `contains`; if a starting value such as `StructuredDocument` is used in `requires`, seed it with `put(producedBy, STRUCTURED_DOCUMENT, document)` in addition to setting the convenience `document` field.
- For multiple generic collections, introduce typed result DTOs and distinct capability ids. Do not model DAG dependencies with `List.class`.

Observability rules:

- Use `event` for node lifecycle and execution trace.
- Use `warning` for recoverable degraded behavior.
- Use `error` for failures that should remain visible after execution.
- Use `metric` for counts, latency and resource usage.
- Do not write raw document content, credentials, prompts, full LLM payloads or stack traces into context events, warnings, variables or metrics.

---

## 3) Components standards

### 3.1 What is a component in this codebase
`components/*` contains reusable processing units (e.g. enrichers, mappers, processors, aggregators) used by services/agents.

### 3.2 Implementation rules
- Annotate with `@Component`.
- Use constructor injection (Lombok `@RequiredArgsConstructor` or equivalent).
- Keep each component single-purpose and composable.
- Components should not expose HTTP concerns (no request/response handling).
- Place component in correct domain package (`components/phase1`, `components/windowing`, etc.).

### 3.3 Error handling
- Catch exceptions only when you can add domain context or fallback logic.
- Do not swallow exceptions silently.
- Log failures with meaningful operation context.

### 3.4 Mandatory package for `@Component` classes
- All classes annotated with `@Component` **must** be placed under package path `com.velia.components`.
- Organize component classes in thematic sub-packages (examples: `com.velia.components.edt`, `com.velia.components.audit`, `com.velia.components.runtimeconfig`, `com.velia.components.<domain>`).
- Do not place `@Component` classes in unrelated root packages when they represent reusable backend processing units.
- Keep sub-package naming domain-driven and stable to preserve discoverability and consistent dependency wiring.
- Quality gate: any new or moved `@Component` must be reviewed for package placement before merge; component classes outside `com.velia.components.<domain>` are considered non-compliant unless they are framework configuration classes in `config`.

---

## 4) Utility class standards

### 4.1 Utility package placement
- Utility classes must be placed under `com.velia.utils`.
- Prefer domain sub-packages such as `com.velia.utils.notifications`, `com.velia.utils.kb`, `com.velia.utils.tenantdashboard` or `com.velia.utils.<domain>`.
- Avoid catch-all utility classes directly under `com.velia.utils` unless they are already established shared utilities and truly cross-domain.

### 4.2 Utility implementation rules
- Keep utility classes stateless.
- Mark utility classes `final` and add a private constructor.
- Do not inject repositories, services or other Spring beans into utility classes; if dependencies are needed, use a `@Component` under `com.velia.components.<domain>` instead.
- Keep utility methods small, deterministic and explicit about null handling.

---

## 5) Service standards

### 5.1 Service responsibilities
- Orchestrate business logic across repositories/components/queues.
- Keep controllers thin by moving non-trivial flow into services.
- Encapsulate domain policies (validation, ordering, filtering, aggregation).
- Integrate user activity audit for mutating/security-relevant user flows according to `USER_ACTIVITY_AUDIT_INTEGRATION_GUIDELINES.md`.

### 5.2 Implementation rules
- Annotate with `@Service`.
- Use constructor injection.
- Keep method names action-oriented (`buildWindowsForWorkspace`, `getCurrentWeather`, etc.).
- Isolate reusable private methods for validation/normalization.

### 5.3 Transaction and consistency
- For multi-step writes, define clear consistency behavior and error propagation.
- Keep queue enqueue behavior explicit and predictable.

### 5.4 User activity audit
- New mutating or security-relevant features must evaluate audit coverage.
- Add audit events in the owning service, not only in controllers or HMI code.
- Use `UserActivityAuditService.recordSafely(...)` for standard business flows.
- Never include passwords, tokens, prompts, document contents, secrets or full payloads in audit metadata.
- Cover success, denied and failure branches where applicable.
- See `dev-guides/USER_ACTIVITY_AUDIT_INTEGRATION_GUIDELINES.md` before implementing audited flows.

### 5.5 Persistent notification policy
- Every new or changed service flow must explicitly evaluate whether it should produce a persistent notification.
- Persistent notifications are for user attention, action, ownership changes, security/access changes, async workflow outcomes and operational failures; they are not a replacement for audit, logs, MQTT state sync or UI toasts.
- Generate notifications from the owning service or a domain component invoked by that service, never directly from controllers, repositories, DTOs or frontend code.
- Prefer a focused notifier component under `com.velia.components.notifications` when notification composition is non-trivial or shared across multiple services.
- Notify when an event requires human attention or action: escalations, failed processing, failed delivery, blocked workflow, denied/changed access or a terminal state that changes what a user must do next.
- Notify when ownership or responsibility changes: assignment, reassignment, handoff, closure/resolution that must be visible to an assignee, or a comment that requires another participant's attention.
- Notify for async workflow terminal outcomes: success only when the user explicitly started the workflow and expects completion feedback; failure when the user, organization profile or administrator must know that intervention may be needed.
- Notify for security/account/access events that materially change risk or availability: password change, account disabled/deleted, impersonation, privilege/scope changes and suspicious or policy-relevant access changes.
- Notify for system degradation only when it is persistent, aggregated or high impact; do not notify each transient retry, polling failure or scheduler iteration.
- Do not notify ordinary CRUD, view/read operations, login/logout, autosaves, internal progress stages, expected validation failures already shown in the UI, or events fully covered by a local toaster.
- Use audit for traceability, logs for diagnostics, MQTT for live state synchronization and notifications for attention/action.
- Notification metadata must be minimal and safe: include stable identifiers, status, category, request/correlation UUIDs and scope; never include passwords, tokens, prompts, document contents, generated content, stack traces, raw payloads or sensitive error details.
- Every notification-producing flow must define recipients explicitly and must skip creation when no readable recipient exists.
- Every notification-producing flow must define a stable `dedupeKey` based on event type, resource UUID, terminal status and request/correlation id where available.
- Unit tests must cover positive notification creation, recipient selection, dedupe-relevant fields and at least one "do not notify" branch for noise control.
- See `dev-guides/notification-code-change-plan-2026-07-02.md` for domain-specific notification phases and examples.

---

## 6) Controller standards

### 6.1 REST structure
- Annotate class with `@RestController` and `@RequestMapping`.
- Keep endpoint naming resource-oriented and consistent (`/api/<domain>`).
- Return `ResponseEntity<T>` with explicit HTTP statuses.

### 6.2 Controller responsibilities
- Validate incoming request presence/basic preconditions.
- Delegate business logic to services/components.
- Perform only HTTP-level orchestration and mapping.

### 6.3 Dependency injection
- Prefer constructor injection (Lombok-based patterns are already used in current controllers).

### 6.4 Response and error behavior
- Use clear status codes (`200`, `201`, `404`, etc.) matching endpoint semantics.
- Keep error mapping centralized in `controlleradvices` when possible.

### 6.5 REST controller compliance checklist (mandatory for `/api/**`)
- Use `@Tag` on every REST controller.
- Use `@Operation` + `@ApiResponses` on every exposed endpoint.
- Prefer `ResponseEntity<T>` for explicit HTTP status handling.
- Keep controller methods thin: request parsing, auth/scope checks, HTTP mapping only.
- Delegate domain/defaulting/composition logic to services.
- Use constructor injection only.

### 6.6 MVC template/fragment controllers (non-REST)
- Controllers serving server-rendered views (`@Controller`, Thymeleaf fragments/pages) are **not required** to use Swagger annotations.
- They must still keep low complexity and delegate reusable composition logic to services/helpers when logic grows.
- Add lightweight logging for non-trivial flows (`debug`/`info`) to preserve observability.

---

## 7) Logging standards (based on current codebase)

### 7.1 Logging framework and style
Current standard in code:
- SLF4J + Lombok `@Slf4j`.
- Parameterized logging (`log.info("... {}", value)`) instead of string concatenation.

### 7.2 Recommended log levels
- `debug` → technical flow details (window parameters, counts, intermediate states).
- `info` → main business flow milestones (request received, queued, saved).
- `warn` → recoverable anomalies or invalid/empty input conditions.
- `error` → failures/exceptions that impact flow.

### 7.3 Logging content rules
- Always include key identifiers in logs when available (`missionId`, `workspaceUuid`, record `uuid`).
- Prefer concise, context-rich messages that describe operation + target.
- Avoid logging sensitive content or full payloads unless strictly needed.
- For exceptions, include meaningful message context (avoid empty error messages).

### 7.4 Consistency checklist
- One start-flow info log where useful.
- One completion log for relevant async/queue actions.
- Warn logs for non-fatal branch conditions.
- Error logs with operation context and exception stack trace.
- For REST controllers, include at least one contextual log in validation-denied/error branches.

---

## 8) Swagger / OpenAPI documentation standards (based on current codebase)

### 8.1 Controller-level documentation
Use:
- `@Tag(name = "...", description = "...")` on each controller class.

### 8.2 Endpoint-level documentation
Use:
- `@Operation(summary = "...", description = "...")` on each endpoint.
- `@ApiResponses` with explicit `@ApiResponse` for major HTTP outcomes.
- `@Parameter` for path/query params with description and examples.

### 8.3 DTO-level documentation
Use:
- `@Schema` on DTO classes and fields exposed via API.
- Field descriptions should be operationally meaningful and concise.

### 8.4 Documentation quality rules
- Keep summaries short and action-focused.
- Keep descriptions explicit about mission/workspace scope.
- Ensure response codes in docs match actual controller behavior.
- Update Swagger docs whenever endpoint contract changes.
- Swagger requirements apply to REST controllers under `/api/**`; exclude MVC template/fragment controllers.

---

## 9) Code quality standards (mandatory)

### 9.1 Cyclomatic complexity must stay low
- Keep methods focused and short, with clear single-purpose behavior.
- Prefer extracting private helper methods rather than growing conditional branches in a single method.
- Avoid deeply nested `if/else` structures when guard clauses or dedicated methods can reduce complexity.

### 9.2 Do not throw generic runtime exceptions
- Do **not** throw `RuntimeException` directly in application code.
- Define and use specific domain/application exceptions (under `exceptions/*`) that clearly represent the failure context.
- Map these exceptions to explicit HTTP/API behavior through `controlleradvices` when exposed through REST endpoints.
- For async orchestrators/pipelines, define dedicated exception types at minimum for:
  - request validation failures (e.g. `*RequestValidationException`);
  - unsupported/mismatched routing/discriminator cases (e.g. `*UnsupportedRequestTypeException`);
  - pipeline execution failures wrapping lower-level causes (e.g. `*PipelineExecutionException`).

### 9.3 Null type safety is mandatory
- New or changed code must avoid null type-safety warnings and obvious `NullPointerException` paths.
- Validate public/service entry-point inputs with guard clauses before dereferencing.
- Normalize nullable external data at boundaries (request DTOs, repositories, integrations) before passing it deeper into domain logic.
- Do not pass nullable values into methods that require non-null inputs; either guard, default, or change the method contract.
- Prefer `Objects.requireNonNull(...)`, explicit validation, or domain-specific `requireText(...)` helpers where absence is invalid.
- Preserve Lombok null-safety intent when present (`@NonNull`) and do not bypass constructor/field guarantees with ad hoc setters.
- When using builders, set non-null defaults for required collection/map/status fields with `@Builder.Default` where appropriate.

### 9.4 Use `Optional` where null-safety is at risk
- Use `Optional` for method contracts where absence is an expected and valid outcome.
- Prefer explicit `Optional` handling to prevent implicit null propagation and reduce `NullPointerException` risks.
- Do not use `Optional` for entity fields/DTO fields; use it for return types and local flow control.

---

## 10) SonarQube-inspired quality gates

These gates translate SonarQube-style quality checks into mandatory review criteria for backend changes.
They are focused on new or changed code, following the Clean as You Code principle.

### 10.1 New-code quality gate
- New code must not introduce blocker or critical issues.
- New code must not introduce vulnerabilities.
- New security hotspots must be reviewed and either fixed or explicitly accepted with a short rationale.
- New-code coverage target is 80% or higher for behavior-bearing code; exceptions must be justified in the PR or implementation notes.
- New-code duplicated lines should stay at or below 3%; duplicated business logic must be extracted or intentionally documented.
- Reliability, security and maintainability ratings for new code should remain at A level where SonarQube is available.

### 10.2 Complexity and maintainability
- Cognitive complexity must remain low; split methods that accumulate nested branching, multiple responsibilities or hard-to-follow control flow.
- Avoid "brain methods" and "monster classes"; move reusable processing into focused components under `com.velia.components.<domain>`.
- Avoid methods with too many parameters; prefer request/command DTOs or small domain value objects.
- Avoid boolean selector parameters in public/service methods when separate action-oriented methods would be clearer.
- Remove unused private methods, fields, imports, parameters and dead branches.
- `TODO` and `FIXME` comments require a ticket, owner or concrete follow-up note; stale TODO/FIXME comments should be removed.

### 10.3 Spring-specific rules
- Constructor injection is mandatory for Spring beans; field injection is not allowed.
- Do not inject dependencies into static fields.
- Do not combine incompatible Spring annotations such as `@Cacheable` and `@CachePut` on the same method unless the behavior is explicitly verified.
- Do not call Spring-proxied behavior through `this` when the proxy is required (`@Transactional`, `@Async`, caching, security).
- `@Scheduled` methods must be no-arg methods and must not depend on request/session state.
- Optional REST parameters should use object types, not primitives, so absence can be represented safely.

### 10.4 Resource and I/O safety
- Use try-with-resources for `Closeable`/`AutoCloseable` resources.
- Do not leave streams, readers, HTTP responses, database cursors or file handles open across method exits.
- Validate and normalize file paths derived from input; do not concatenate untrusted path segments directly.
- Check return values from I/O methods when they signal partial reads, failed writes or status codes.
- Avoid `deleteOnExit()` in server code.

### 10.5 Security-sensitive coding
- Never hardcode credentials, tokens, API keys, secrets, private keys or passwords.
- Never log secrets, credentials, tokens, raw prompts, document contents or full sensitive payloads.
- Do not build SQL, JSONPath, XML, shell commands, templates or filesystem paths through unsafe concatenation of untrusted input.
- Use parameterized queries and framework APIs for query construction.
- XML parsers must be configured defensively when parsing external or user-controlled XML.
- Clear-text protocols, weak TLS behavior and disabled hostname verification require explicit documented approval.
- Regular expressions that process external input must avoid catastrophic backtracking risk.

### 10.6 Duplicates, constants and literals
- Repeated string literals used as keys, statuses, actions, error codes, routes, topics or metadata names must be extracted to constants or enums.
- Magic numbers in business logic must be named constants unless they are obvious local values such as `0`, `1` or collection limits already documented by context.
- Avoid duplicating validation, mapping and access-control logic; extract shared behavior into a component or utility in the correct domain package.
- Do not extract one-off UI/user-facing copy or test-only literals solely to satisfy duplication rules when extraction would reduce readability.

### 10.7 Collections and mutability
- Do not modify a collection while iterating over it unless using an iterator-supported removal pattern.
- Do not expose mutable internal collections directly from domain objects or components.
- Prefer `List.copyOf`, `Set.copyOf`, `Map.copyOf`, `List.of`, `Set.of` and `Map.of` when returning or storing immutable snapshots.
- Use base collection interfaces (`List`, `Set`, `Map`) in method parameters unless implementation-specific behavior is required.
- Avoid raw types.

### 10.8 Tests and assertions
- New behavior-bearing code must have focused tests, especially for reliability, security, null-safety and authorization branches.
- Tests must contain meaningful assertions; tests that only verify "no exception" need an explicit reason.
- Test names should describe the behavior and expected outcome.
- Avoid `Thread.sleep` in tests; use deterministic synchronization, fake clocks or polling helpers with bounded timeouts.
- Keep test code in dedicated test source directories and avoid production-only shortcuts in tests.

### 10.9 Logging and exception hygiene
- Do not use `System.out`, `System.err` or `printStackTrace()` for application diagnostics.
- Log through SLF4J with parameterized messages.
- Catch blocks must either handle the exception, add meaningful context or convert it to a domain/application exception.
- Do not catch broad exceptions just to rethrow the same exception without context.
- Do not swallow exceptions silently.

## 11) Definition of done (backend)

A backend feature is considered complete when:
- Classes are in correct package/layer and domain sub-package.
- `@Component` classes are placed under `com.velia.components` with thematic sub-packages.
- Utility classes are placed under `com.velia.utils` with thematic sub-packages when domain-specific.
- Agent classes are placed under `com.velia.agents` with thematic sub-packages.
- DTOs follow current Lombok/Jackson/Schema/Data annotations pattern.
- Business logic is in services/components, not controllers.
- New or changed code is free from null type-safety warnings and has explicit null-boundary handling.
- New or changed code satisfies the SonarQube-inspired gates for complexity, duplication, security, resources and tests.
- Logging follows SLF4J levels and includes contextual identifiers.
- Swagger/OpenAPI annotations are complete and aligned with real behavior.
- Repository/index decisions are explicit for persisted DTOs.
- Exceptions are handled with clear API behavior.
- Developer documentation in `docs/` is updated.
