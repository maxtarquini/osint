# Agent Class Structure Guidelines (Based on `EventDomainClassifierAgent`)

## Purpose
This guide defines a consistent structure for Java agent classes in this codebase, with special focus on:
- application logging (`@Slf4j` + `log.*`)
- lifecycle publishing through `AgentActivityPublisher`

It is derived from the implementation patterns used by example agents under `src/main/java/com/velia/agents/example`.

Raven note: this guide applies to application-level AI execution units that use Spring, model clients, queues, prompt loaders and lifecycle publishers. It does not apply to the engine-independent workflow agent contracts under `it.osint.raven.workflow.agent`. Those contracts are pure domain interfaces and must not use Spring annotations, direct loggers, LangChain4j/OpenAI clients, queue handles, prompt loaders or persistence clients.

---

## 0. Agent package placement (mandatory)

- All agents must be under package root `com.velia.agents`.
- Organize agents in thematic sub-packages (for example `com.velia.agents.edt`, `com.velia.agents.classification`, `com.velia.agents.<domain>`).
- Keep assistant interfaces co-located in the same thematic agent package when possible.

---

## 1. Class-Level Shape

Agent-support components used by agent classes (mappers, prompt loaders, enrichers) must follow `dev-guides/BACKEND_JAVA_DEVELOPMENT_GUIDELINES.md` and stay under `com.velia.components` thematic packages.


Each agent class should follow this baseline structure:

1. **Spring and Lombok annotations**
   - `@Component`
   - `@Scope("prototype")`
   - `@Slf4j`
   - `@RequiredArgsConstructor(onConstructor = @__(@Autowired))`

2. **Configuration flags**
   - `@Value("${ollama.model.logRequests}")`
   - `@Value("${ollama.model.logResponses}")`

3. **Injected dependencies (`@NonNull`)**
   - `ObjectMapper`
   - Prompt/module loader(s)
   - `VeliaNodesRequestQueue`
   - `PlatformAuditLogger`
   - `AgentActivityPublisher` (recommended for lifecycle telemetry)

4. **Single public entry method** (e.g., `classify`, `convert`, `enrich`)
   - Declares checked exceptions where needed.
   - Handles the complete workflow: start activity, acquire node, invoke model, parse output, release resources, finalize activity.

5. **Private helper methods**
   - Keep output transformation and mapping logic separate (e.g., `applyFlags`).

---

## 2. Lifecycle Contract with `AgentActivityPublisher`

Use lifecycle events in a deterministic way:

### Required pattern

1. **Before main work starts**
   - Generate `instanceUuid` (`UUID.randomUUID().toString()`).
   - Capture `startedAt` (`System.currentTimeMillis()`).
   - Publish `publishStarted(...)` with:
     - agent name (constant string matching class name)
     - instance UUID
     - phase (e.g., `PHASE1`)
     - meaningful message (e.g., "Classifying event domains")

2. **While in progress**
   - Publish at least one `publishRunning(...)` event when entering the core operation.
   - Include a semantic stage label (e.g., `CLASSIFICATION`) and coarse progress percentage.

3. **Always finalize in `finally`**
   - Publish `publishFinished(...)` exactly once.
   - Duration must be computed as `System.currentTimeMillis() - startedAt`.
   - Final message should describe successful completion of the high-level task.

### Error-path recommendation

If an exception can occur in core logic, add an explicit failure publication before rethrowing:
- use a dedicated failure event method if available (preferred), or
- publish a final state/message that clearly marks failure.

Even in failure paths, keep resource cleanup (`prompt logger clear`, queue node return) in `finally`.

---

## 3. Logging Guidelines (`log.info`, `log.warn`, `log.error`)

`EventDomainClassifierAgent` currently relies mostly on activity publisher telemetry and prompt file logging. For new/updated agents, use both telemetry and structured logs:

1. **`log.info` for key milestones**
   - Start of operation (include agent instance UUID).
   - Model/node selected (never log secrets).
   - End of operation with elapsed time.

2. **`log.warn` for recoverable anomalies**
   - Missing optional inputs.
   - Partial response content.
   - Fallback/default-path activation.

3. **`log.error` for hard failures**
   - Include exception and correlation fields (`agentName`, `instanceUuid`, primary domain/event id if present).

4. **Do not log sensitive payloads**
   - Avoid raw full user messages if they may include sensitive information.
   - Prefer IDs, counts, and domain labels.

5. **Prefer parameterized logging**
   - `log.info("Domain category: {}", domain)`
   - Avoid string concatenation in logging calls.

---

## 4. Prompt Logger and Node Queue Discipline

Inside the public entry method:

1. Set prompt logger context before model interaction:
   - `platformAuditLogger.setCurrentAgentName("<AgentClassName>")`

2. Acquire node using queue `take()`.

3. Build `OllamaChatModel` with:
   - node URL/model name
   - timeout
   - `logRequests` + `logResponses`
   - listeners including `platformAuditLogger`

4. In `finally`:
   - clear current agent name
   - return node to queue with `put(...)`

This cleanup must execute regardless of success/failure.

---

## 5. Suggested Canonical Method Skeleton

```java
public OutputDto execute(InputDto input) throws Exception {
    final String agentName = "MyAgent";
    final String instanceUuid = UUID.randomUUID().toString();
    final long startedAt = System.currentTimeMillis();

    agentActivityPublisher.publishStarted(agentName, instanceUuid, "PHASE1", null, null, "Starting task");
    agentActivityPublisher.publishRunning(agentName, instanceUuid, "PHASE1", null, null, "STAGE", "Running task", 50);

    Optional<NodeDto> node = Optional.empty();
    try {
        platformAuditLogger.setCurrentAgentName(agentName);
        node = Optional.of(veliaNodesRequestQueue.getQueue().take());

        // Build model, call assistant, parse response
        return result;
    } catch (Exception ex) {
        log.error("{} failed. instanceUuid={}", agentName, instanceUuid, ex);
        throw ex;
    } finally {
        platformAuditLogger.clearCurrentAgentName();
        if (node.isPresent()) {
            veliaNodesRequestQueue.getQueue().put(node.get());
        }
        agentActivityPublisher.publishFinished(
            agentName,
            instanceUuid,
            "PHASE1",
            null,
            null,
            System.currentTimeMillis() - startedAt,
            "Task completed"
        );
    }
}
```

---

## 6. Quality Checklist for New Agent Classes

- [ ] Uses prototype scope and constructor injection.
- [ ] Has `logRequests` / `logResponses` config flags.
- [ ] Publishes started/running/finished activity events.
- [ ] Correlates telemetry and logs with a single `instanceUuid`.
- [ ] Uses `try/finally` cleanup for prompt logger and queue node.
- [ ] Uses `log.info/warn/error` at appropriate severity.
- [ ] Avoids sensitive-data logging.
- [ ] Keeps transformation logic in private helper methods.
