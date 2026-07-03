# Multi-Agent Multi-RAG Chat — Development Plan

**Date:** 2026-06-17  
**Scope:** Extend `EnterpriseDigitalTwinChatAgent` with a LangGraph4j-based orchestration layer that supports multiple domain-specific RAG agents and a synthesis agent.  
**LangGraph4j ref:** https://github.com/langgraph4j/langgraph4j (stable line: `1.8.x`; verify the latest Maven Central version before implementation, e.g. `1.8.19` was current on 2026-06-17)

---

## 1. Context and Current Architecture

The current chat pipeline is a single-agent, single-RAG flow:

```
ChatRequest
  └─► EnterpriseDigitalTwinChatService
        ├─► EnterpriseDigitalTwinChatRagContextResolver   (single KB retrieval)
        └─► EnterpriseDigitalTwinChatAgent               (single LLM call)
```

**Limitations:**
- One knowledge base per chat request (user selects it manually via `knowledgeBaseUuid`).
- Frontend chat state tracks a single active KB; commands currently support `/USE` and reset-style removal only.
- The entire RAG context is injected into a single prompt — context window fills up fast when many KBs exist.
- No query decomposition: complex cross-domain questions are answered with a single LLM pass.

---

## 2. Target Architecture

```
ChatRequest
  └─► MultiAgentChatOrchestrationService
        └─► [LangGraph4j CompiledGraph]
              ├─ orchestrator    → ChatOrchestratorAgent  (decompose + route)
              ├─ domainWorkers   → ChatDomainWorkerAgent  (one Qdrant search + partial answer per selected KB)
              └─ synthesis       → ChatSynthesisAgent     (merge partials + EDT context → final response)
```

Three nodes map to three agent roles:

| Node key | Agent class | Responsibility |
|---|---|---|
| `orchestrator` | `ChatOrchestratorAgent` | Analyse query, select relevant KBs, produce sub-queries |
| `domainWorkers` | `ChatDomainWorkerAgent` | Embed each sub-query, search its dedicated Qdrant collection, generate partial answer |
| `synthesis` | `ChatSynthesisAgent` | Merge partial answers, format final coherent response |

---

## 3. LangGraph4j Integration

### 3.1 Maven Dependencies

LangGraph4j publishes a BOM and core module. Add the core dependency first; add LangChain4j integration modules only if the implementation actually uses LangGraph4j-provided LangChain4j adapters. The existing chat agents already use LangChain4j directly, so `langgraph4j-core` is sufficient for the initial graph wiring.

```xml
<properties>
    <langgraph4j.version>1.8.19</langgraph4j.version>
</properties>

<!-- BOM — manages all langgraph4j module versions -->
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.bsc.langgraph4j</groupId>
            <artifactId>langgraph4j-bom</artifactId>
            <version>${langgraph4j.version}</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>

<dependencies>
    <!-- Core graph engine -->
    <dependency>
        <groupId>org.bsc.langgraph4j</groupId>
        <artifactId>langgraph4j-core</artifactId>
    </dependency>

    <!-- Optional: add the exact LangChain4j integration artifact only if needed.
         Verify the artifact name for the selected LangGraph4j version
         (the 1.8.x repo contains langchain4j-core and langchain4j-agent modules). -->
</dependencies>
```

> The groupId is `org.bsc.langgraph4j` (not `io.github.bsorrentino`).  
> Minimum Java version supported by LangGraph4j: **Java 17** (project uses Java 21 ✓).  
> Always check [Maven Central](https://central.sonatype.com/search?q=g%3Aorg.bsc.langgraph4j) for the latest release before adding.
> Current project note: `pom.xml` already uses `dev.langchain4j:langchain4j` and `dev.langchain4j:langchain4j-ollama` version `1.13.0`, plus `langchain4j-qdrant` version `1.13.0-beta23`; dependency compatibility must be checked before merging.

### 3.2 Core LangGraph4j Concepts

**`AgentState`** is the shared mutable state passed between nodes. It is backed by a `Map<String, Object>` and a channel schema (`Map<String, Channel<?>>`). The schema defines how each key's value is merged when a node returns an update:

- `Channel.Default.of(defaultValue)` — last-write-wins (overwrites previous value).
- `Channels.appender(ArrayList::new)` — appends to a list; used for accumulating results across nodes.

**`NodeAction<S>`** / **`AsyncNodeAction<S>`** — functional interface for a node. Receives the current `AgentState` subclass, returns `Map<String, Object>` with state updates. The keys must match the schema.

**`StateGraph<S>`** — builder for the graph; accepts the schema and a state constructor. Compile with `.compile()` to get a `CompiledGraph<S>`.

**Execution:**
- `compiledGraph.stream(inputMap)` — returns an `Iterable` yielding the state after each node.
- `compiledGraph.invoke(inputMap)` — returns `CompletableFuture<S>` with the final state.

**`START` / `END`** — special sentinel constants imported from `org.bsc.langgraph4j.StateGraph`.

### 3.3 Graph State — `MultiAgentChatState`

Package: `com.velia.dto.chat.multiagent`

The state must **extend `AgentState`** (not be a plain Lombok DTO). Typed accessors expose the underlying map entries.

```java
import org.bsc.langgraph4j.state.AgentState;
import org.bsc.langgraph4j.state.Channel;
import org.bsc.langgraph4j.state.Channels;

public class MultiAgentChatState extends AgentState {

    // Channel schema — defines merge strategy for every key
    public static final Map<String, Channel<?>> SCHEMA = Map.of(
            "userMessage",              Channel.Default.of(""),
            "enterpriseDigitalTwinJson",Channel.Default.of(""),
            "conversationContextJson",  Channel.Default.of(""),
            "selectedKnowledgeBaseUuid", Channel.Default.of(""),
            "selectedKnowledgeBaseUuids", Channel.Default.of(List.of()),
            "availableKnowledgeBases",  Channel.Default.of(List.of()),
            "subQueries",               Channels.appender(ArrayList::new),
            "partialAnswers",           Channels.appender(ArrayList::new),
            "aggregatedSources",        Channels.appender(ArrayList::new),
            "finalAnswer",              Channel.Default.of(""),
            "errorMessage",             Channel.Default.of("")
    );

    public MultiAgentChatState(Map<String, Object> initData) {
        super(initData);
    }

    public String userMessage() {
        return this.<String>value("userMessage").orElse("");
    }

    public String enterpriseDigitalTwinJson() {
        return this.<String>value("enterpriseDigitalTwinJson").orElse("");
    }

    public String conversationContextJson() {
        return this.<String>value("conversationContextJson").orElse("");
    }

    public String selectedKnowledgeBaseUuid() {
        return this.<String>value("selectedKnowledgeBaseUuid").orElse("");
    }

    @SuppressWarnings("unchecked")
    public List<String> selectedKnowledgeBaseUuids() {
        return (List<String>) this.value("selectedKnowledgeBaseUuids").orElse(List.of());
    }

    @SuppressWarnings("unchecked")
    public List<KnowledgeBaseDto> availableKnowledgeBases() {
        return (List<KnowledgeBaseDto>) this.value("availableKnowledgeBases").orElse(List.of());
    }

    @SuppressWarnings("unchecked")
    public List<ChatDomainSubQueryDto> subQueries() {
        return (List<ChatDomainSubQueryDto>) this.value("subQueries").orElse(List.of());
    }

    @SuppressWarnings("unchecked")
    public List<ChatDomainPartialAnswerDto> partialAnswers() {
        return (List<ChatDomainPartialAnswerDto>) this.value("partialAnswers").orElse(List.of());
    }

    @SuppressWarnings("unchecked")
    public List<OrganizationChatRagSourceDto> aggregatedSources() {
        return (List<OrganizationChatRagSourceDto>) this.value("aggregatedSources").orElse(List.of());
    }

    public String finalAnswer() {
        return this.<String>value("finalAnswer").orElse("");
    }
}
```

Supporting DTOs (same package, standard Lombok + Swagger annotations per codebase conventions):

- `ChatDomainSubQueryDto` — `{ domainKey, subQuery, knowledgeBaseUuid }`
- `ChatDomainPartialAnswerDto` — `{ domainKey, knowledgeBaseUuid, partialAnswer, sources, ragContext }`

### 3.4 Graph Definition — `MultiAgentChatGraphFactory`

Package: `com.velia.components.edt.chat.multiagent`

```java
import org.bsc.langgraph4j.StateGraph;
import org.bsc.langgraph4j.action.AsyncNodeAction;
import static org.bsc.langgraph4j.action.AsyncNodeAction.node_async;
import static org.bsc.langgraph4j.StateGraph.START;
import static org.bsc.langgraph4j.StateGraph.END;

@Component
@RequiredArgsConstructor
@Slf4j
public class MultiAgentChatGraphFactory {

    private final ChatOrchestratorAgent orchestratorAgent;
    private final ChatDomainWorkerAgent domainWorkerAgent;
    private final ChatSynthesisAgent synthesisAgent;

    public CompiledGraph<MultiAgentChatState> build() throws GraphStateException {
        return new StateGraph<>(MultiAgentChatState.SCHEMA, MultiAgentChatState::new)
                .addNode("orchestrator",  node_async(orchestratorAgent::run))
                .addNode("domainWorkers", node_async(domainWorkerAgent::runAll))
                .addNode("synthesis",     node_async(synthesisAgent::run))
                .addEdge(START, "orchestrator")
                .addEdge("orchestrator", "domainWorkers")
                .addEdge("domainWorkers", "synthesis")
                .addEdge("synthesis", END)
                .compile();
    }
}
```

> Each node method (`run`, `runAll`) must have signature:
> `Map<String, Object> run(MultiAgentChatState state) throws Exception`
>
> `node_async(ref)` is a static helper from `org.bsc.langgraph4j.action.AsyncNodeAction` that wraps a synchronous `NodeAction` into the required `AsyncNodeAction` returning `CompletableFuture`.

---

## 4. New Agent Classes

All agents must follow `dev-guides/AGENT_CLASS_STRUCTURE_GUIDELINES.md`:
- `@Component @Scope("prototype") @Slf4j @RequiredArgsConstructor(onConstructor = @__(@Autowired))`
- Acquire/release `VeliaNodesRequestQueue` node in `try/finally`
- Publish `AgentRuntimeEventPublisher` lifecycle events (started / running / finished)
- Correlate logs with `instanceUuid`
- Return `Map<String, Object>` with the exact keys declared in `MultiAgentChatState.SCHEMA`

Implementation note: these classes are both graph node actions and LLM agents. Keep them under `com.velia.agents.chat.multiagent` because they directly execute model calls. Pure graph factories/components stay under `com.velia.components`.

### 4.1 `ChatOrchestratorAgent`

Package: `com.velia.agents.chat.multiagent`

**Responsibility:** Given the user message and available KB metadata, produce a list of `ChatDomainSubQueryDto` (one per relevant KB). LLM returns a JSON array; parse with Jackson.

**Node method signature:**

```java
public Map<String, Object> run(MultiAgentChatState state) throws Exception {
    // 1. Build orchestrator prompt with KB names/descriptions and user message
    // 2. Acquire Ollama node, call LLM, parse JSON array into List<ChatDomainSubQueryDto>
    // 3. Return state update
    return Map.of("subQueries", parsedSubQueries);
}
```

**System prompt (summary):**
> You are a routing orchestrator. Given the user question, optional selected Knowledge Base UUIDs, and the list of available knowledge bases (name, description, uuid), output a JSON array of sub-queries — one per relevant knowledge base. Each sub-query refines the original question for that domain. If selected Knowledge Base UUIDs are provided, treat them as the active RAG scope and route only to relevant KBs from that selected set. Ignore selected UUIDs that are not present in the candidate list. If no selected UUIDs are provided, auto-select from all candidates. Return an empty array `[]` if no KB is relevant.

**Assistant interface:** `ChatOrchestratorAssistant` — LangChain4j `@SystemMessage` / `@UserMessage` pattern, co-located in same package.

### 4.2 `ChatDomainWorkerAgent`

Package: `com.velia.agents.chat.multiagent`

**Responsibility:** For each `ChatDomainSubQueryDto` in state:
1. Embed the sub-query using `OllamaEmbeddingModel`.
2. Search the dedicated Qdrant collection through the existing `OrganizationChatRagRetrievalService.retrieve(knowledgeBase, subQuery.getSubQuery())`.
3. Format retrieved chunks as RAG context.
4. Run an LLM call to produce a `partialAnswer` grounded in that context.
5. Collect sources.

**Node method signature:**

```java
public Map<String, Object> runAll(MultiAgentChatState state) throws Exception {
    List<ChatDomainPartialAnswerDto> partialAnswers = new ArrayList<>();
    List<OrganizationChatRagSourceDto> sources = new ArrayList<>();

    for (ChatDomainSubQueryDto subQuery : state.subQueries()) {
        // acquire node, embed, search Qdrant, call LLM, release node
        partialAnswers.add(partialAnswer);
        sources.addAll(partialAnswer.getSources());
    }

    return Map.of(
        "partialAnswers",    partialAnswers,
        "aggregatedSources", sources
    );
}
```

Because the state uses `Channels.appender`, the returned lists are **appended** to the existing state values (not replaced). This is intentional for multi-turn or subgraph scenarios.

**Parallelism:** Initial implementation is sequential (simpler, lower risk). Parallel fan-out using `CompletableFuture` can be added in Phase 7 once correctness is proven. Do not share a single `OllamaNodeHandle` across worker tasks; let existing retrieval and LLM code acquire/release queue handles per task.

**System prompt (summary):**
> You are a domain expert assistant. Answer the given sub-question using ONLY the retrieved knowledge base context. If the context contains no relevant evidence, reply exactly: "No relevant evidence found in this domain."

**Assistant interface:** `ChatDomainWorkerAssistant` (same package).

### 4.3 `ChatSynthesisAgent`

Package: `com.velia.agents.chat.multiagent`

**Responsibility:** Merge all partial answers into a single coherent response. If there are no selected KBs or no useful evidence, answer from the Enterprise Digital Twin and conversation context only, and clearly state when no Knowledge Base evidence was found.

**Node method signature:**

```java
public Map<String, Object> run(MultiAgentChatState state) throws Exception {
    // Build synthesis prompt from state.partialAnswers(), state.userMessage(),
    // state.enterpriseDigitalTwinJson(), state.conversationContextJson()
    // Acquire node, call LLM, return final answer
    return Map.of("finalAnswer", synthesizedAnswer);
}
```

**System prompt (summary):**
> You are a synthesis agent. Combine the following partial domain answers into a single, coherent, non-redundant response suitable for a business dashboard. Cite only evidence from the domain answers. Do not invent information.

**Assistant interface:** `ChatSynthesisAssistant` (same package).

---

## 5. Service and Component Changes

### 5.1 New service: `MultiAgentChatOrchestrationService`

Package: `com.velia.services`

```java
@Service
@RequiredArgsConstructor
@Slf4j
public class MultiAgentChatOrchestrationService {

    private final MultiAgentChatGraphFactory graphFactory;
    private final ChatKnowledgeBaseRegistryComponent kbRegistry;
    private final ObjectMapper objectMapper;

    @Value("${enterprise-digital-twin.chat.multi-agent.graph-timeout-seconds:300}")
    private long graphTimeoutSeconds;

    public EnterpriseDigitalTwinChatResponseDto answer(
            UserDTO caller,
            EnterpriseDigitalTwinChatRequestDto request,
            EnterpriseDigitalTwinDto edt,
            List<EnterpriseDigitalTwinChatMessageDto> conversationContext)
            throws Exception {

        List<KnowledgeBaseDto> availableKbs = kbRegistry.listAccessible(caller, request.getOrganizationUuid());

        Map<String, Object> initialInput = Map.of(
                "userMessage",               request.getMessage(),
                "enterpriseDigitalTwinJson", objectMapper.writeValueAsString(edt),
                "conversationContextJson",   objectMapper.writeValueAsString(conversationContext),
                "selectedKnowledgeBaseUuid", request.getKnowledgeBaseUuid() == null ? "" : request.getKnowledgeBaseUuid(),
                "selectedKnowledgeBaseUuids", resolveSelectedKnowledgeBaseUuids(request),
                "availableKnowledgeBases",   availableKbs
        );

        MultiAgentChatState finalState = graphFactory.build()
                .invoke(initialInput)   // returns CompletableFuture<MultiAgentChatState>
                .get(graphTimeoutSeconds, TimeUnit.SECONDS);

        return buildResponse(finalState);
    }
}
```

### 5.2 New component: `ChatKnowledgeBaseRegistryComponent`

Package: `com.velia.components.edt.chat.multiagent`

Fetches candidate KB metadata for the caller by reusing `KnowledgeBaseService.listKnowledgeBasesInScope(caller)`. It must filter candidates to:
- `KnowledgeBaseStatus.ACTIVE`;
- global KBs (`GLOBAL_ADMIN`) plus KBs owned by `request.organizationUuid`;
- only KBs readable by the caller (already enforced by `KnowledgeBaseService`).

This does not replace `EnterpriseDigitalTwinChatKnowledgeBaseSelector`, which remains the read/list helper for the existing UI and single-agent path. The new registry provides full `KnowledgeBaseDto` records because `OrganizationChatRagRetrievalService.retrieve(...)` requires `KnowledgeBaseDto`, not `KnowledgeBaseViewDto`.

### 5.3 `EnterpriseDigitalTwinChatService` changes

Add a feature flag `enterprise-digital-twin.chat.multi-agent.enabled` (default: `false`).

```java
if (multiAgentEnabled) {
    EnterpriseDigitalTwinDto twin = loadTwin(caller, request.getOrganizationUuid(), false);
    return multiAgentChatOrchestrationService.answer(caller, request, twin, request.getConversationContext());
} else {
    // existing single-agent path — unchanged
}
```

This branch should be placed in `answer(...)` after `requestValidator.validateChatRequest(request)` and before `ragContextResolver.retrieveRagContext(...)`, so multi-agent mode does not perform the legacy single-KB retrieval first. `streamAnswer(...)` remains on the existing single-agent path until streaming is explicitly implemented for the graph.

Constructor note: `EnterpriseDigitalTwinChatService` currently has an explicit production constructor and a package-private test constructor. Add `MultiAgentChatOrchestrationService` and the feature flag without breaking existing tests; either update the test constructor with a nullable/disabled multi-agent dependency or introduce a small configuration holder with safe defaults.

### 5.4 Multi-KB selection in request DTO

Keep `knowledgeBaseUuid` optional for backward compatibility and add a new optional list field:

```java
@JsonProperty("knowledge_base_uuids")
@Schema(description = "Optional selected Knowledge Base UUIDs for multi-KB RAG grounding")
private List<String> knowledgeBaseUuids;
```

Selection resolution rules:
- If `knowledgeBaseUuids` is non-empty, use it as the selected KB set for multi-agent mode.
- Else if legacy `knowledgeBaseUuid` is present, treat it as a single-element selected set.
- Else selected set is empty and the orchestrator may auto-select from all accessible candidate KBs.
- If multi-agent is disabled, keep the existing single-agent behavior and use only `knowledgeBaseUuid`; do not silently fan out through `knowledgeBaseUuids`.
- If a selected UUID is inaccessible, absent, deleted, or outside the requested organization/global scope, the registry candidate list is authoritative and the orchestrator ignores it. The single-agent path keeps its current strict lookup behavior.

Response shape remains unchanged: all evidence from one or more KBs is returned in `ragSources`.

### 5.5 Frontend multi-KB commands

Update `chat-shell-renderer.js` and chat i18n strings so the chat can maintain an ordered active KB selection list.

No new backend command endpoint is required for the first implementation: `/ADD`, `/REMOVE`, `/USE`, and `/KB` can reuse the existing `GET /api/organization-chat/knowledge-bases/resolve` endpoint to resolve names to `OrganizationChatKnowledgeBaseSelectionDto`. `/REMOVE` by UUID can operate directly on the local active list without a backend lookup when the UUID is already selected.

Command semantics:
- `/ADD knowledge base name` resolves a visible KB by name and adds it to the active RAG KB list. If it is already selected, keep the list unchanged and show a short status message.
- `/REMOVE knowledge base name` resolves/removes the matching KB from the active list. It should also accept an exact selected UUID for copy/paste convenience. Removing a KB that is not active should not fail the chat; show a short status message.
- `/USE knowledge base name` remains available and keeps its current syntax, but its effect changes to replace the whole active KB list with the resolved KB. This preserves existing user muscle memory while giving deterministic “single KB only” behavior.
- `/KB knowledge base name` remains an alias for `/USE`.
- `/RESET` and `/NO_KB` clear the whole active KB list.
- `/STATUS` must show all active KBs, not just one.
- `/LIST` remains unchanged and still lists accessible KBs.

Message payload behavior:
- When the active list contains exactly one KB, send both `knowledge_base_uuid` and `knowledge_base_uuids` for backward compatibility.
- When the active list contains more than one KB, send `knowledge_base_uuids` and omit `knowledge_base_uuid` or set it to the first selected UUID only if legacy server compatibility is required. The multi-agent backend must use `knowledge_base_uuids` as authoritative.
- When the active list is empty, send neither field.

UI state naming recommendation:
- Replace `selectedKnowledgeBase` with `selectedKnowledgeBases` (`Array<OrganizationChatKnowledgeBaseSelectionDto>`).
- Preserve ordering by insertion so `/STATUS` and request payloads are deterministic.
- De-duplicate by `uuid`.

### 5.6 Streaming support

Initial implementation targets the non-streaming `answer` path only. LangGraph4j `stream()` yields one state per completed node, which can be used to push status updates via `ChatStreamingCallback.onStatus()`. Full token-level streaming from the synthesis node is deferred to a follow-up.

---

## 6. Memory Management

### 6.1 Intra-request shared memory (team memory)

`MultiAgentChatState` is the shared team memory within one graph invocation. LangGraph4j manages state transitions between nodes; no external store is needed for intra-request coordination.

### 6.2 Short-term agent memory

Each node execution is self-contained. All intermediate results accumulate in the state via `Channels.appender` reducers and are available to downstream nodes.

### 6.3 Cross-turn conversation memory

The existing `conversationContextJson` (serialised list of `EnterpriseDigitalTwinChatMessageDto`) is passed unchanged into the initial state and forwarded to the synthesis agent. No changes needed.

### 6.4 Checkpointing (optional, for debugging / resumability)

LangGraph4j provides `CheckpointSaver` implementations out of the box:
- `MemorySaver` — in-process, suitable for development/testing.
- `langgraph4j-postgres-saver`, `langgraph4j-mysql-saver`, `langgraph4j-oracle-saver` — persistent, for production.

To enable, pass a saver to `graph.compile(CompileConfig.builder().checkpointSaver(new MemorySaver()).build())`.

For the initial rollout, checkpointing is optional but recommended for debugging complex multi-agent runs.

---

## 7. DTO and API Changes

### 7.1 New DTOs

Package: `com.velia.dto.chat.multiagent` — all follow codebase conventions (`@Data @Builder @NoArgsConstructor @AllArgsConstructor`, `@Schema` at class and field level, `@JsonIgnoreProperties(ignoreUnknown = true)`).

- `ChatDomainSubQueryDto`
- `ChatDomainPartialAnswerDto`

> Note: `MultiAgentChatState` extends `AgentState` (not a DTO). Do not annotate it with Lombok builders.

### 7.2 `EnterpriseDigitalTwinChatResponseDto`

Do not add a new sources field for the first rollout. Reuse the existing `ragSources` field for both single-agent and multi-agent modes:
- single-agent mode: sources from the selected KB, current behavior;
- multi-agent mode: aggregated worker sources across all selected KBs.

This preserves the API shape while still allowing the UI to display multiple KB sources, because `OrganizationChatRagSourceDto` already includes `knowledgeBaseUuid` and `knowledgeBaseName`.

### 7.3 `EnterpriseDigitalTwinChatRequestDto`

Add `knowledgeBaseUuids` while keeping `knowledgeBaseUuid`:

```java
@Getter
@Setter
@Builder.Default
@JsonProperty("knowledge_base_uuids")
@Schema(description = "Optional selected Knowledge Base UUIDs for multi-KB RAG grounding")
private List<String> knowledgeBaseUuids = new ArrayList<>();
```

The validator should normalize blank/null entries away and enforce that the list is optional, not required. Access validation happens in the KB registry/retrieval path.

---

## 8. Configuration Properties

```properties
# Feature flag
enterprise-digital-twin.chat.multi-agent.enabled=false

# Max KBs the orchestrator may route to in one request
enterprise-digital-twin.chat.multi-agent.max-domains=5

# CompletableFuture.get() timeout for the full graph execution (seconds)
enterprise-digital-twin.chat.multi-agent.graph-timeout-seconds=300
```

---

## 9. Observability — LangGraph4j Studio

LangGraph4j ships a built-in web UI (Studio) for visualising and debugging graphs. Add the Spring Boot module for development environments:

```xml
<dependency>
    <groupId>org.bsc.langgraph4j</groupId>
    <artifactId>langgraph4j-studio-springboot</artifactId>
    <!-- scope: provided or test only — not for production -->
    <scope>provided</scope>
</dependency>
```

Studio renders the graph structure (PlantUML / Mermaid diagrams) and lets you inspect the state after each node. Activate only in `dev` Spring profile. The exact Studio artifact name is version-sensitive; verify it for the selected LangGraph4j release before adding it to `pom.xml`.

---

## 10. Package Summary

```
com.velia.agents.chat.multiagent
    ChatOrchestratorAgent.java
    ChatOrchestratorAssistant.java
    ChatDomainWorkerAgent.java
    ChatDomainWorkerAssistant.java
    ChatSynthesisAgent.java
    ChatSynthesisAssistant.java

com.velia.components.edt.chat.multiagent
    MultiAgentChatGraphFactory.java
    ChatKnowledgeBaseRegistryComponent.java

com.velia.dto.chat.multiagent
    MultiAgentChatState.java            (extends AgentState — NOT a Lombok DTO)
    ChatDomainSubQueryDto.java
    ChatDomainPartialAnswerDto.java

com.velia.dto.chat
    EnterpriseDigitalTwinChatRequestDto.java  (modified — add knowledgeBaseUuids)

com.velia.services
    MultiAgentChatOrchestrationService.java   (new)
    EnterpriseDigitalTwinChatService.java     (modified — feature flag branch)
```

---

## 11. Development Phases

### Phase 1 — Foundation

1. Add `langgraph4j-bom` and `langgraph4j-core` to `pom.xml`; add LangChain4j integration modules only if implementation needs them.
2. Verify no version conflicts with existing `langchain4j 1.13.0`, `langchain4j-ollama 1.13.0`, and `langchain4j-qdrant 1.13.0-beta23` dependencies.
3. Create `ChatDomainSubQueryDto` and `ChatDomainPartialAnswerDto` in `com.velia.dto.chat.multiagent`.
4. Create `MultiAgentChatState` extending `AgentState` with full schema and typed accessors.
5. Add `knowledgeBaseUuids` to `EnterpriseDigitalTwinChatRequestDto` while preserving legacy `knowledgeBaseUuid`.
6. Unit-test state schema: verify appender channels accumulate correctly, default channels overwrite.

### Phase 2 — Orchestrator Agent

1. Implement `ChatOrchestratorAssistant` interface and `ChatOrchestratorAgent`.
2. Implement `ChatKnowledgeBaseRegistryComponent` backed by `KnowledgeBaseService.listKnowledgeBasesInScope`.
3. Unit-test orchestrator with mocked LLM: verify JSON sub-query parsing, KB selection, empty-array edge case.
4. Quality gate: orchestrator routes correctly on at least 5 representative cross-domain queries and never routes outside `selectedKnowledgeBaseUuids` when the active set is non-empty.

### Phase 3 — Domain Worker Agent

1. Implement `ChatDomainWorkerAssistant` and `ChatDomainWorkerAgent` (sequential fan-out).
2. Reuse `OrganizationChatRagRetrievalService` for embedding + Qdrant search per sub-query.
3. Unit-test with mocked Qdrant and mocked LLM.
4. Quality gate: partial answer is grounded in retrieved context; "no evidence" path returns sentinel text; aggregated sources are correct.

### Phase 4 — Synthesis Agent

1. Implement `ChatSynthesisAssistant` and `ChatSynthesisAgent`.
2. Unit-test with varied partial answer sets (empty, single-domain, multi-domain, conflicting).
3. Quality gate: synthesis is shorter than the sum of partials; all cited sources appear in `aggregatedSources`.

### Phase 5 — Graph Wiring and Service Integration

1. Implement `MultiAgentChatGraphFactory`.
2. Implement `MultiAgentChatOrchestrationService`.
3. Add feature flag branch in `EnterpriseDigitalTwinChatService`, preserving the existing single-agent `answer` and `streamAnswer` behavior.
4. Resolve active KB selection from `knowledgeBaseUuids` first, then legacy `knowledgeBaseUuid`.
5. Build `EnterpriseDigitalTwinChatResponseDto` with `ragSources = finalState.aggregatedSources()`.
6. Integration test: invoke graph end-to-end with in-memory mocks, verify state transitions and final response shape.
7. Enable Studio in `dev` profile only after verifying the artifact for the selected LangGraph4j version.

### Phase 5b — Chat UI Multi-KB Commands

1. Update `chat-shell-renderer.js` state from one `selectedKnowledgeBase` to ordered `selectedKnowledgeBases`.
2. Add `/ADD` and `/REMOVE` command handlers using the existing `/api/organization-chat/knowledge-bases/resolve` endpoint.
3. Change `/USE` and `/KB` to replace the entire active KB list with one resolved KB.
4. Change `/RESET` and `/NO_KB` to clear all active KBs.
5. Update `/STATUS`, composer KB state, command help, and i18n strings in `hmi/core/i18n.js`.
6. Update message payload generation to send `knowledge_base_uuids` for multi-agent mode.
7. Frontend quality gate: `/ADD A`, `/ADD B`, normal message sends both UUIDs; `/REMOVE A` sends only B; `/USE C` sends only C; `/RESET` sends no KBs.

### Phase 6 — Rollout and Observability

1. Enable feature flag on staging with 1–2 KBs.
2. Add `AgentRuntimeEventPublisher` graph-level lifecycle events (graph started / graph finished / per-node transitions).
3. Verify `instanceUuid` propagation across all three agent nodes for end-to-end telemetry correlation.
4. Measure latency per node, total latency vs. single-agent baseline.
5. Gradually enable on production with monitoring.

### Phase 7 (follow-up) — Parallel Worker Execution

Replace the sequential fan-out in `ChatDomainWorkerAgent` with a `CompletableFuture`-based parallel implementation using the existing `VeliaNodesRequestQueue` pool. Benchmark latency improvement.

---

## 12. Quality Gates (per `AGENT_CLASS_STRUCTURE_GUIDELINES.md`)

All new agent classes must satisfy:

- [ ] `@Component @Scope("prototype")` with constructor injection.
- [ ] `AgentRuntimeEventPublisher` started / running / finished lifecycle.
- [ ] Single `instanceUuid` correlating all logs and telemetry within one execution.
- [ ] `try/finally` cleanup: prompt logger cleared, queue node returned.
- [ ] Node method returns `Map<String, Object>` keyed exactly to `MultiAgentChatState.SCHEMA`.
- [ ] No sensitive payload logging (no raw user messages, no full JSON at INFO level).
- [ ] Unit tests with mocked LLM and mocked Qdrant for each agent.
- [ ] `ChatDomainSubQueryDto` and `ChatDomainPartialAnswerDto` have `@Schema` at class and field level.
- [ ] `@JsonIgnoreProperties(ignoreUnknown = true)` on DTOs used for LLM JSON output parsing.
- [ ] Multi-agent response populates existing `ragSources`; no duplicate `multiAgentSources` API field in Phase 1.
- [ ] `ChatKnowledgeBaseRegistryComponent` does not expose KBs outside caller scope or the requested organization/global scope.
- [ ] `EnterpriseDigitalTwinChatRequestDto` supports `knowledge_base_uuids` without breaking legacy `knowledge_base_uuid`.
- [ ] Chat UI implements `/ADD`, `/REMOVE`, `/USE`, `/KB`, `/RESET`, `/NO_KB`, `/STATUS` with deterministic multi-KB state.
- [ ] `/USE` replaces the active KB list; `/ADD` appends; `/REMOVE` deletes; duplicate add/remove-not-present cases are handled gracefully.

---

## 13. Open Questions / Decisions Needed

| # | Question | Impact |
|---|---|---|
| 1 | Should the orchestrator use a lighter/faster model for routing vs. the same model as workers? | Cost, latency |
| 2 | Hard cap of 5 KBs per request (`max-domains`) or configurable per organization? | Scope |
| 3 | Parallel worker fan-out in Phase 3 or deferred to Phase 7? | Latency vs. complexity |
| 4 | Should `knowledgeBaseUuid` in the request DTO remain a strong hint forever, or become only a legacy single-agent field once multi-agent mode is stable? | API compatibility |
| 5 | Activate `MemorySaver` checkpointing in dev from day one, or add later? | Debugging velocity |
| 6 | Token-level streaming from synthesis node: emit tokens via `ChatStreamingCallback.onToken()` or deliver full response only? | UX |
| 7 | Should `/REMOVE` support partial-name matching or require the same exact name/UUID resolution used by `/USE` and `/ADD`? | UX ambiguity |
