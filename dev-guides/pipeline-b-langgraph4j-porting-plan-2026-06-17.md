# Pipeline B → LangGraph4j Porting Plan

**Date:** 2026-06-17  
**Last reviewed:** 2026-06-19
**Scope:** Replace the imperative `EdtPipelineBTwinGenerationService` sequential pipeline with a stateful, multi-agent LangGraph4j graph, enabling parallel document preparation, parallel domain planning, explicit state checkpointing, and better observability.  
**LangGraph4j ref:** https://github.com/langgraph4j/langgraph4j (stable line: `1.8.x`; verify the latest Maven Central version before implementation, e.g. `1.8.19` was current on 2026-06-17)

---

## 1. Current Pipeline B — As-Is Analysis

### 1.1 Entry Point and Trigger

Pipeline B is triggered by a queue message (`EdtTwinGenerationRequestDto`) consumed by `EdtRequestFacadeProcessor`, which dispatches to `EdtPipelineBTwinGenerationService.execute()`.

### 1.2 Execution Flow (sequential, imperative)

```
EdtPipelineBTwinGenerationService.execute(EdtTwinGenerationRequestDto)
  │
  ├─ [B0] intake: loadOrInitRun, validateRequest, load OrganizationDocuments
  │
  ├─ [B1] PreparationAgentsGate.prepare(documents)
  │         └─ for each document (sequential):
  │               PreprationAgent.prepare(document)   ← LLM call per document
  │               sets document.documentPreparationByDomain
  │
  ├─ [B2] PlanningAgentsGate.plan(documents, organizationUuid)
  │         └─ EdtPlannerAgent.generatePlan(input)
  │               ├─ aggregateDomains(documents)         ← groups docs by domain
  │               └─ buildAggrergatedDomainPlan per domain (sequential switch-case):
  │                     identity   → IdentityDomainPlanner.plan()     [rule-based]
  │                     financial  → FinanceDomainPlanner.plan()      [rule-based]
  │                     compliance → ComplianceDomainPlanner.plan()   [rule-based]
  │                     business   → BusinessDomainPlanner.plan()     [rule-based]
  │                                  + BusinessDomainPlanExecutor.execute()
  │                                    └─ ProfileDiscrepacyDetectionAgent.detect() ← LLM call
  │                     operations → OperationsDomainPlanner.plan()   [rule-based]
  │
  └─ [B3] FinalizationAgentsGate.finalizeTwin(plan, context, documents)
            └─ EdtFinalizationAgent.finalizeTwin(...)
                  └─ for each domainPlan (sequential switch-case):
                        identity   → IdentityDomainProcessor.addDomainData()   [rule-based]
                        financial  → FinancialDomainProcessor.addDomainData()  [rule-based]
                        compliance → ComplianceDomainProcessor.addDomainData() [rule-based]
                        business   → BusinessDomainProcessor.addDomainData()
                                      └─ BusinessDomainFusionAgent.fuse() ← LLM call
                                         when HIGH_CONFIDENCE_BUSINESS_CONSOLIDATION applies
```

### 1.3 LLM-Calling Agents in Pipeline B

| Agent | Phase | Call type |
|---|---|---|
| `PreprationAgent` | B1 Preparation | One LLM call per document (N calls total) |
| `ProfileDiscrepacyDetectionAgent` | B2 Planning / Business | One LLM call (conditional on `DETECT_NARRATIVE_DISCREPANCIES` rule) |
| `BusinessDomainFusionAgent` | B3 Finalization / Business | One LLM call when `BusinessDomainProcessor` performs high-confidence business profile fusion |

All other planners and processors are pure rule-based Java logic — no LLM.

### 1.3.1 Current Implementation Caveats

- `OperationsDomainPlanner.plan(...)` currently throws `UnsupportedOperationException`. A graph node wrapping it is not a harmless no-op if documents with domain `operations` are present.
- The legacy `EdtPlannerAgent.generatePlan(...)` catches broad exceptions and logs them without rethrowing. The graph path should improve this behavior, but that is a behavior change and must be captured in the migration quality gates.
- Several finalization processors catch `JsonProcessingException` internally and continue. Functional parity tests must decide whether the graph reproduces this tolerant behavior first, then hardens it in a later change, or intentionally changes the failure contract from Phase 1.

### 1.4 State Tracking (current)

- `EdtGenerationRunDto` (MongoDB) stores `status` + `stage` string — updated at each phase boundary.
- `TwinGenerationContextDto` is an in-memory holder passed between methods.
- No intermediate state persistence between phases; a crash loses all work done so far.

### 1.5 Key Problems with the Current Design

| Problem | Impact |
|---|---|
| All N document preparations run sequentially | High latency when organization has many documents |
| All 5 domain planners run sequentially | Unnecessary: domains are fully independent |
| Crash between phases loses all progress | Full re-run required; expensive re-LLM-calls |
| No structured error path per phase | Generic try/catch, difficult to diagnose failures |
| `switch-case` routing is rigid | Adding a new domain requires touching `EdtPlannerAgent` and `EdtFinalizationAgent` |
| State tracked only as stage strings in MongoDB | No ability to inspect intermediate structured state |

---

## 2. Target Architecture — LangGraph4j Graph

### 2.1 Macro Graph (Phase 1: sequential, safe migration)

```
START
  └─► intake
  └─► prepareDocuments          ← PreprationAgent × N (sequential, then parallel in Phase 2)
  └─► aggregateDomains          ← pure Java: group docs by domain
  └─► planIdentity              ← IdentityDomainPlanner (conditional: skipped if no identity docs)
  └─► planFinance               ← FinanceDomainPlanner  (conditional)
  └─► planCompliance            ← ComplianceDomainPlanner (conditional)
  └─► planBusiness              ← BusinessDomainPlanner + BusinessDomainPlanExecutor/LLM (conditional)
  └─► planOperations            ← OperationsDomainPlanner (conditional)
  └─► mergeGenerationPlan       ← collect one planned domain per domain → EdtGenerationPlanDto
  └─► initTwin                  ← initialize EnterpriseDigitalTwinDto with org/doc metadata
  └─► finalizeIdentity          ← IdentityDomainProcessor (conditional)
  └─► finalizeFinancial         ← FinancialDomainProcessor (conditional)
  └─► finalizeCompliance        ← ComplianceDomainProcessor (conditional)
  └─► finalizeBusiness          ← BusinessDomainProcessor (conditional; may invoke BusinessDomainFusionAgent/LLM)
  └─► mergeTwin                 ← assemble final EnterpriseDigitalTwinDto
  └─► persistTwin               ← save to MongoDB, update EdtGenerationRunDto
END
```

### 2.2 Macro Graph (Phase 2: parallel fan-out)

```
START
  └─► intake
  └─► prepareDocuments          ← `ParallelPrepareDocumentsNode` fan-out per document
  └─► aggregateDomains
  ├──────────────────────────────────────────────────────────────┐
  ├─► planIdentity              ← parallel branches (LangGraph4j parallel edges)
  ├─► planFinance
  ├─► planCompliance
  ├─► planBusiness
  └─► planOperations
  └──────────────────────────────────────────────────────────────┘
  └─► mergeGenerationPlan       ← fan-in: collect one planned domain per domain
  └─► initTwin
  └─► finalizeIdentity          ← sequential in Phase 2; parallelization deferred
  └─► finalizeFinancial
  └─► finalizeCompliance
  └─► finalizeBusiness
  └─► mergeTwin
  └─► persistTwin
END
```

### 2.3 EDT Creation Workflow to Reproduce in LangGraph4j

The graph must reproduce the EDT creation workflow exactly before any parallel optimization is enabled:

```
queue request
  └─► validate request and load/create EdtGenerationRunDto
  └─► load OrganizationDocumentDto records for organizationUuid
  └─► build TwinGenerationContextDto
  └─► prepare each document
        └─ skip documents that already have documentPreparationByDomain
        └─ call PreprationAgent only for missing preparation
        └─ persist each prepared OrganizationDocumentDto
  └─► create EdtGenerationPlanDto shell
  └─► aggregate prepared documents by documentDomain
        └─ add inputDocumentTypes
        └─ add documentsPreparation
        └─ set domain status AVAILABLE
        └─ set latestPlannerRunUuid and append plannerRunUuids on each document
  └─► run domain planners
        └─ identity, financial, compliance, business, operations only when domain shell exists
        └─ business may invoke ProfileDiscrepacyDetectionAgent during planning
        └─ operations must follow the explicit policy chosen in section 13
  └─► persist final EdtGenerationPlanDto
  └─► initialize EnterpriseDigitalTwinDto with organizationUuid and source document metadata
  └─► run domain finalizers sequentially
        └─ identity populates identity
        └─ financial appends finance data
        └─ compliance currently preserves EDT unchanged
        └─ business may populate profile and narrativeDiscrepancies, and may call BusinessDomainFusionAgent
  └─► normalize/validate final EDT
  └─► delete existing EDT by organizationUuid and save the new EDT
  └─► update EdtGenerationRunDto to COMPLETED
```

Phase 1 success means the graph produces the same persisted `EnterpriseDigitalTwinDto`, `EdtGenerationPlanDto`, document planner metadata, and run status as the legacy pipeline for the same fixed inputs and deterministic/mocked LLM responses.

---

## 3. Graph State — `EdtPipelineBState`

Package: `com.velia.dto.edt.pipelineb.graph`

Extends `AgentState` (LangGraph4j requirement). All keys must be declared in the static `SCHEMA`.

```java
import org.bsc.langgraph4j.state.AgentState;
import org.bsc.langgraph4j.state.Channel;
import org.bsc.langgraph4j.state.Channels;

public class EdtPipelineBState extends AgentState {

    public static final Map<String, Channel<?>> SCHEMA = Map.ofEntries(
        // ── Input ──────────────────────────────────────────────────
        Map.entry("requestDto",          Channel.Default.of(null)),
        Map.entry("organizationUuid",    Channel.Default.of("")),
        Map.entry("correlationId",       Channel.Default.of("")),

        // ── Lifecycle ───────────────────────────────────────────────
        Map.entry("runDto",              Channel.Default.of(null)),
        Map.entry("stage",               Channel.Default.of("B0_INTAKE")),
        Map.entry("errorMessage",        Channel.Default.of("")),
        Map.entry("failedNode",          Channel.Default.of("")),

        // ── Runtime context ─────────────────────────────────────────
        Map.entry("context",             Channel.Default.of(null)),

        // ── Documents ───────────────────────────────────────────────
        // raw: loaded from MongoDB before preparation
        Map.entry("rawDocuments",        Channel.Default.of(List.of())),
        // prepared: accumulated by prepareDocuments node (appender because
        // parallel fan-out will write one entry per document)
        Map.entry("preparedDocuments",   Channels.appender(ArrayList::new)),

        // ── Planning ────────────────────────────────────────────────
        // shell plans produced by aggregateDomains, before domain-specific rules.
        Map.entry("domainPlanShells",    Channel.Default.of(Map.of())),
        // planned domain outputs. Planner branches append independently; fan-in
        // validates that there is exactly one planned output per domain.
        Map.entry("plannedDomainPlans",  Channels.appender(ArrayList::new)),
        Map.entry("generationPlan",      Channel.Default.of(null)),

        // ── Finalization ────────────────────────────────────────────
        Map.entry("enterpriseDigitalTwin", Channel.Default.of(null))
    );

    public EdtPipelineBState(Map<String, Object> initData) { super(initData); }

    // Typed accessors
    public EdtTwinGenerationRequestDto requestDto() { ... }
    public String organizationUuid() { ... }
    public EdtGenerationRunDto runDto() { ... }
    public String stage() { ... }
    public TwinGenerationContextDto context() { ... }
    public List<OrganizationDocumentDto> rawDocuments() { ... }
    public List<OrganizationDocumentDto> preparedDocuments() { ... }
    public Map<String, EdtDomainPlanDto> domainPlanShells() { ... }
    public List<EdtDomainPlanDto> plannedDomainPlans() { ... }
    public EdtGenerationPlanDto generationPlan() { ... }
    public EnterpriseDigitalTwinDto enterpriseDigitalTwin() { ... }
    public String errorMessage() { ... }
    public String failedNode() { ... }
}
```

> **Why `Channels.appender` for `preparedDocuments` and `plannedDomainPlans`?**
> In Phase 2, each parallel document-preparation branch writes its result independently. `appender` reduces merge correctly: each branch returns `Map.of("preparedDocuments", List.of(oneResult))` and LangGraph4j concatenates them. The same pattern is used for `plannedDomainPlans`, but only planner nodes write to it; `domainPlanShells` remains a map keyed by domain to avoid duplicate shell + planned entries in the final `EdtGenerationPlanDto`.
>
> Parallel append order is not guaranteed. Before `aggregateDomains`, the prepared documents must be restored to the original `rawDocuments` order, or a deterministic ordering by document UUID must be explicitly chosen and applied in both graph and legacy comparison tests.

---

## 4. Node Definitions

All node classes live in `com.velia.components.edt.pipelineb.graph.nodes` (new sub-package alongside the existing `planning/`, `preparation/`, `finalization/`). Each node is a Spring `@Component` following the component rules in `BACKEND_JAVA_DEVELOPMENT_GUIDELINES.md`. Nodes that directly invoke LLM agents must also preserve the relevant lifecycle and logging rules from `AGENT_CLASS_STRUCTURE_GUIDELINES.md`; nodes that only delegate to existing agents rely on those agents for queue/prompt cleanup.

Node method signature: `Map<String, Object> execute(EdtPipelineBState state) throws Exception`

### 4.1 `IntakeNode`

Replaces: `loadOrInitRun` + `validateRequest` + `organizationDocumentRepository.findByOrganizationUuid`.

```java
public Map<String, Object> execute(EdtPipelineBState state) throws Exception {
    EdtTwinGenerationRequestDto request = state.requestDto();
    validateRequest(request);
    EdtGenerationRunDto run = loadOrInitRun(request);
    run = saveRun(run.withStatus(RUNNING).withStage("B0_INTAKE"));
    TwinGenerationContextDto context = buildContext(request);
    List<OrganizationDocumentDto> documents = documentRepository
            .findByOrganizationUuid(request.getOrganizationUuid());
    return Map.of(
        "runDto",         run,
        "context",        context,
        "rawDocuments",   documents,
        "stage",          "B1_PREPARATION"
    );
}
```

### 4.2 `PrepareDocumentsNode`

Replaces: `PreparationAgentsGate.prepare()`.

**Phase 1 (sequential):** iterate `state.rawDocuments()`, call existing `PreprationAgent.prepare(doc)` for each document that has no `documentPreparationByDomain` yet.

**Phase 2 (parallel):** use `ParallelPrepareDocumentsNode` with `CompletableFuture` fan-out inside a single graph node. Each task resolves a fresh prototype `PreprationAgent` through `ObjectProvider`, and the agent still acquires an `OllamaNodeHandle` from `VeliaNodesRequestQueue`; this keeps queue-based LLM throttling while avoiding concurrent reuse of one agent instance. The node returns prepared documents in the original `rawDocuments` order, regardless of task completion order.

```java
public Map<String, Object> execute(EdtPipelineBState state) throws Exception {
    List<OrganizationDocumentDto> prepared = new ArrayList<>();
    for (OrganizationDocumentDto doc : state.rawDocuments()) {
        if (doc.getDocumentPreparationByDomain() == null) {
            doc.setDocumentPreparationByDomain(preprationAgent.prepare(doc));
        }
        documentRepository.save(doc);
        prepared.add(doc);
    }
    return Map.of(
        "preparedDocuments", prepared,   // appended to state
        "stage",             "B2_PLANNING"
    );
}
```

### 4.3 `AggregateDomainsNode`

Replaces: `EdtPlannerAgent.aggregateDomains()`.

Pure Java — no LLM. Groups prepared documents by `documentDomain`, builds one `EdtDomainPlanDto` shell per domain (without rules yet). It also applies the same metadata side effects currently performed by `EdtPlannerAgent`: set `latestPlannerRunUuid`, append the planner run UUID to each document, and save the document. The full `EdtGenerationPlanDto` is persisted only after domain planning, in `MergeGenerationPlanNode`.

Idempotency requirement: when this node is re-run with the same `generationPlan.uuid`, it must not append a duplicate entry to `document.plannerRunUuids`. Use an explicit contains check before appending.

```java
public Map<String, Object> execute(EdtPipelineBState state) {
    EdtGenerationPlanDto generationPlan = EdtGenerationPlanDto.builder()
            .organizationUuid(state.organizationUuid())
            .build();
    Map<String, EdtDomainPlanDto> plansByDomain = new LinkedHashMap<>();
    for (OrganizationDocumentDto doc : state.preparedDocuments()) {
        EdtDomainPlanDto domainPlan = plansByDomain.computeIfAbsent(
            doc.getDocumentDomain(),
            d -> EdtDomainPlanDto.builder().domain(d).build());
        domainPlan.getInputDocumentTypes().add(doc.getDocumentType());
        domainPlan.getDocumentsPreparation().add(doc.getDocumentPreparationByDomain());
        domainPlan.setStatus(PlannerDomainStatus.AVAILABLE.name());
        doc.setLatestPlannerRunUuid(generationPlan.getUuid());
        if (!doc.getPlannerRunUuids().contains(generationPlan.getUuid())) {
            doc.getPlannerRunUuids().add(generationPlan.getUuid());
        }
        organizationDocumentRepository.save(doc);
    }
    return Map.of(
        "generationPlan",    generationPlan,
        "domainPlanShells",  Map.copyOf(plansByDomain),
        "stage",             "B2_DOMAIN_PLANNING"
    );
}
```

### 4.4 Domain Planner Nodes

One node per domain. Each wraps the existing `*DomainPlanner` (rule-based, no LLM) or the `BusinessDomainPlanExecutor` (which has the LLM call).

All follow the same pattern — example for identity:

```java
// PlanIdentityNode
public Map<String, Object> execute(EdtPipelineBState state) {
    EdtDomainPlanDto domainPlan = findDomainPlanShell(state, "identity");
    if (domainPlan == null) return Map.of();   // domain absent: no-op
    identityDomainPlanner.plan(domainPlan);
    return Map.of("plannedDomainPlans", List.of(domainPlan));   // appended
}
```

`PlanBusinessNode` additionally calls `businessDomainPlanExecutor.execute(domainPlan)` (LLM via `ProfileDiscrepacyDetectionAgent`).

Nodes:
- `PlanIdentityNode` → wraps `IdentityDomainPlanner`
- `PlanFinanceNode` → wraps `FinanceDomainPlanner`
- `PlanComplianceNode` → wraps `ComplianceDomainPlanner`
- `PlanBusinessNode` → wraps `BusinessDomainPlanner` + `BusinessDomainPlanExecutor`
- `PlanOperationsNode` → Phase 1 fail-fast guard for operations documents while `OperationsDomainPlanner` remains unimplemented.

Operations policy for Phase 1:
- `skip-operations`: if an operations shell exists, mark it as not available or omit it and log a warning. This preserves graph completion but changes behavior relative to the current throwing planner.
- `fail-fast` (**chosen for Phase 1**): throw a dedicated `EdtPipelineBUnsupportedDomainException` when operations documents are present. This is safer and explicit, but can block EDT generation for organizations with operations documents.
- `implement-operations`: implement the rule set before wiring `PlanOperationsNode`; this is the only option that makes operations a first-class domain in Phase 1.

### 4.5 `MergeGenerationPlanNode`

Fan-in: collects the accumulated `plannedDomainPlans` from state into a final `EdtGenerationPlanDto` and persists it. Before persisting, deduplicate by `domain` and fail fast if two planner branches produced the same domain, because the final plan must contain exactly one entry per domain present in the prepared documents.

```java
public Map<String, Object> execute(EdtPipelineBState state) {
    Map<String, EdtDomainPlanDto> byDomain = new LinkedHashMap<>();
    for (EdtDomainPlanDto domainPlan : state.plannedDomainPlans()) {
        EdtDomainPlanDto previous = byDomain.putIfAbsent(domainPlan.getDomain(), domainPlan);
        if (previous != null) {
            throw new EdtPipelineBGraphException("Duplicate domain plan: " + domainPlan.getDomain());
        }
    }
    EdtGenerationPlanDto plan = state.generationPlan();
    plan.setDomainPlans(List.copyOf(byDomain.values()));
    plan.setCreatedAt(Instant.now());
    edtGenerationPlanRepository.save(plan);
    return Map.of("generationPlan", plan, "stage", "B3_FINALIZATION");
}
```

### 4.6 `InitTwinNode`

Replaces the initialization part of `EdtFinalizationAgent.initEdt(...)`. It creates the mutable `EnterpriseDigitalTwinDto` before sequential finalizers run, and fills `organizationUuid`, `sourceDocumentsUuids`, and `sourceDocumentsTypes` from `state.preparedDocuments()`.

```java
public Map<String, Object> execute(EdtPipelineBState state) {
    EnterpriseDigitalTwinDto edt = EnterpriseDigitalTwinDto.builder()
            .organizationUuid(state.organizationUuid())
            .build();
    for (OrganizationDocumentDto document : state.preparedDocuments()) {
        edt.getSourceDocumentsUuids().add(document.getUuid());
        edt.getSourceDocumentsTypes().add(document.getDocumentType());
    }
    return Map.of("enterpriseDigitalTwin", edt);
}
```

### 4.7 Domain Finalizer Nodes

One node per domain, wrapping existing `*DomainProcessor.addDomainData()`. Identity, financial, and compliance are rule-based. Business finalization may call `BusinessDomainFusionAgent`, therefore `FinalizeBusinessNode` must be treated as an LLM-capable node for timeout, telemetry, queue pressure, and checkpoint design.

Each node reads the matching `EdtDomainPlanDto` from `state.generationPlan()`, calls the processor, and writes the updated `EnterpriseDigitalTwinDto` back. Because processors mutate the EDT in-place, the finalization nodes must run sequentially in Phases 1-3 (shared mutable object). A later dedicated phase may redesign each processor to return an immutable domain slice and let `MergeTwinNode` assemble the final EDT.

- `FinalizeIdentityNode` → wraps `IdentityDomainProcessor`
- `FinalizeFinancialNode` → wraps `FinancialDomainProcessor`
- `FinalizeComplianceNode` → wraps `ComplianceDomainProcessor`
- `FinalizeBusinessNode` → wraps `BusinessDomainProcessor`

### 4.8 `MergeTwinNode`

Validates and normalizes the final `EnterpriseDigitalTwinDto` after sequential finalizers. It must ensure `organizationUuid`, `coveredDomains`, `sourceDocumentsUuids`, and `sourceDocumentsTypes` are populated consistently with `state.generationPlan()` and `state.preparedDocuments()`. In a later finalization-parallelization phase, this node becomes the fan-in point for immutable domain slices.

### 4.9 `PersistTwinNode`

Replaces: `saveStepB2`. Deletes the existing EDT by org UUID, saves the new one, updates `EdtGenerationRunDto` to `COMPLETED`.

```java
public Map<String, Object> execute(EdtPipelineBState state) {
    EnterpriseDigitalTwinDto edt = state.enterpriseDigitalTwin();
    edt.setOrganizationUuid(state.organizationUuid());
    enterpriseDigitalTwinRepository.deleteByOrganizationUuid(edt.getOrganizationUuid());
    enterpriseDigitalTwinRepository.save(edt);
    EdtGenerationRunDto run = saveRun(state.runDto().withStatus(COMPLETED).withStage("B3_DONE"));
    return Map.of("runDto", run, "stage", "COMPLETED");
}
```

### 4.10 Failure Contract for All Nodes

Every node must either:

- return a state update with keys declared in `EdtPipelineBState.SCHEMA`; or
- throw a specific domain/application exception with enough context to update the run as failed.

Do not swallow exceptions in new graph nodes. If the wrapped legacy component swallows an exception internally, document that behavior in the node test and keep it only when required for Phase 1 parity. The graph service is responsible for catching graph-level failures and marking `EdtGenerationRunDto` as `FAILED` with the best-known stage and failed node.

---

## 5. Graph Factory — `EdtPipelineBGraphFactory`

Package: `com.velia.components.edt.pipelineb.graph`

```java
import org.bsc.langgraph4j.StateGraph;
import static org.bsc.langgraph4j.action.AsyncNodeAction.node_async;
import static org.bsc.langgraph4j.StateGraph.START;
import static org.bsc.langgraph4j.StateGraph.END;

@Component
@RequiredArgsConstructor
@Slf4j
public class EdtPipelineBGraphFactory {

    // Use stateless node beans, or ObjectProvider-backed prototype nodes.
    // Do not directly inject prototype nodes into a singleton factory.
    private final IntakeNode intakeNode;
    private final PrepareDocumentsNode prepareDocumentsNode;
    private final AggregateDomainsNode aggregateDomainsNode;
    private final PlanIdentityNode planIdentityNode;
    private final PlanFinanceNode planFinanceNode;
    private final PlanComplianceNode planComplianceNode;
    private final PlanBusinessNode planBusinessNode;
    private final PlanOperationsNode planOperationsNode;
    private final MergeGenerationPlanNode mergeGenerationPlanNode;
    private final FinalizeIdentityNode finalizeIdentityNode;
    private final FinalizeFinancialNode finalizeFinancialNode;
    private final FinalizeComplianceNode finalizeComplianceNode;
    private final FinalizeBusinessNode finalizeBusinessNode;
    private final InitTwinNode initTwinNode;
    private final MergeTwinNode mergeTwinNode;
    private final PersistTwinNode persistTwinNode;

    public CompiledGraph<EdtPipelineBState> build() throws GraphStateException {
        return new StateGraph<>(EdtPipelineBState.SCHEMA, EdtPipelineBState::new)
                // ── Sequential backbone (Phase 1) ─────────────
                .addNode("intake",              node_async(intakeNode::execute))
                .addNode("prepareDocuments",    node_async(prepareDocumentsNode::execute))
                .addNode("aggregateDomains",    node_async(aggregateDomainsNode::execute))
                // ── Domain planners (sequential in Phase 1) ───
                .addNode("planIdentity",        node_async(planIdentityNode::execute))
                .addNode("planFinance",         node_async(planFinanceNode::execute))
                .addNode("planCompliance",      node_async(planComplianceNode::execute))
                .addNode("planBusiness",        node_async(planBusinessNode::execute))
                .addNode("planOperations",      node_async(planOperationsNode::execute))
                // ── Fan-in ────────────────────────────────────
                .addNode("mergeGenerationPlan", node_async(mergeGenerationPlanNode::execute))
                .addNode("initTwin",            node_async(initTwinNode::execute))
                // ── Domain finalizers (sequential in Phase 1) ─
                .addNode("finalizeIdentity",    node_async(finalizeIdentityNode::execute))
                .addNode("finalizeFinancial",   node_async(finalizeFinancialNode::execute))
                .addNode("finalizeCompliance",  node_async(finalizeComplianceNode::execute))
                .addNode("finalizeBusiness",    node_async(finalizeBusinessNode::execute))
                .addNode("mergeTwin",           node_async(mergeTwinNode::execute))
                .addNode("persistTwin",         node_async(persistTwinNode::execute))
                // ── Edges ─────────────────────────────────────
                .addEdge(START,               "intake")
                .addEdge("intake",            "prepareDocuments")
                .addEdge("prepareDocuments",  "aggregateDomains")
                .addEdge("aggregateDomains",  "planIdentity")
                .addEdge("planIdentity",      "planFinance")
                .addEdge("planFinance",       "planCompliance")
                .addEdge("planCompliance",    "planBusiness")
                .addEdge("planBusiness",      "planOperations")
                .addEdge("planOperations",    "mergeGenerationPlan")
                .addEdge("mergeGenerationPlan","initTwin")
                .addEdge("initTwin",          "finalizeIdentity")
                .addEdge("finalizeIdentity",  "finalizeFinancial")
                .addEdge("finalizeFinancial", "finalizeCompliance")
                .addEdge("finalizeCompliance","finalizeBusiness")
                .addEdge("finalizeBusiness",  "mergeTwin")
                .addEdge("mergeTwin",         "persistTwin")
                .addEdge("persistTwin",       END)
                .compile();
    }
}
```

Spring scope note: Phase 1 uses `@Scope("prototype")` nodes resolved through `ObjectProvider<...>` at graph build time. Direct constructor injection into a singleton factory resolves prototype beans only once. A simpler future alternative is to make graph nodes stateless singleton `@Component`s and keep per-run state exclusively inside `EdtPipelineBState`.

---

## 6. New Orchestration Service — `EdtPipelineBGraphService`

Package: `com.velia.services.edt`

Replaces `EdtPipelineBTwinGenerationService` only on the feature-flagged path. Called by `EdtRequestFacadeProcessor` via feature flag. Because this class orchestrates a business flow across graph factory, repositories, and queue-triggered execution, implement it as a Spring `@Service`; keep graph nodes and factory under `com.velia.components`.

```java
@Service
@Scope("prototype")
@RequiredArgsConstructor
@Slf4j
public class EdtPipelineBGraphService {

    private final EdtPipelineBGraphFactory graphFactory;
    private final EdtGenerationRunRepository edtGenerationRunRepository;

    public TwinGenerationContextDto execute(EdtTwinGenerationRequestDto request) throws Exception {
        Map<String, Object> initialInput = Map.of(
                "requestDto",       request,
                "organizationUuid", request.getOrganizationUuid(),
                "correlationId",    request.getCorrelationId() == null ? "" : request.getCorrelationId()
        );

        try {
            EdtPipelineBState finalState = graphFactory.build()
                    .invoke(initialInput)   // CompletableFuture<EdtPipelineBState>
                    .get(graphTimeoutSeconds, TimeUnit.SECONDS);

            if (StringUtils.hasText(finalState.errorMessage())) {
                markFailed(finalState.runDto(), finalState.stage(), finalState.failedNode(), finalState.errorMessage());
            }
            return finalState.context();
        } catch (TimeoutException timeoutException) {
            markLatestRunFailed(request, "GRAPH_TIMEOUT", timeoutException);
            throw new EdtPipelineBGraphException("Pipeline B graph timed out", timeoutException);
        } catch (InterruptedException interruptedException) {
            Thread.currentThread().interrupt();
            markLatestRunFailed(request, "GRAPH_INTERRUPTED", interruptedException);
            throw new EdtPipelineBGraphException("Pipeline B graph interrupted", interruptedException);
        } catch (ExecutionException executionException) {
            markLatestRunFailed(request, "GRAPH_EXECUTION_FAILED", executionException.getCause());
            throw new EdtPipelineBGraphException("Pipeline B graph failed", executionException.getCause());
        }
    }
}
```

The timeout value must come from `enterprise-digital-twin.pipeline-b.graph-timeout-seconds`; do not hardcode `600` in the service.

---

## 7. Feature Flag and Migration Strategy

Add to `application.properties`:

```properties
# Enables the LangGraph4j-based Pipeline B; false = legacy EdtPipelineBTwinGenerationService
enterprise-digital-twin.pipeline-b.graph-enabled=false

# CompletableFuture.get() timeout for the full graph (seconds)
enterprise-digital-twin.pipeline-b.graph-timeout-seconds=600
```

`EdtRequestFacadeProcessor` already dispatches to `EdtPipelineBTwinGenerationService`. Add a branch:

```java
if (pipelineBGraphEnabled) {
    edtPipelineBGraphService.execute((EdtTwinGenerationRequestDto) queueRequest);
} else {
    edtPipelineBTwinGenerationService.execute((EdtTwinGenerationRequestDto) queueRequest);
}
```

The legacy service is **not deleted** until the graph implementation has been validated in production.

---

## 8. Checkpointing

For Pipeline B, checkpointing is particularly valuable: if the process crashes after document preparation (the most expensive step), a `MemorySaver` or `MongoCheckpointSaver` would allow resuming from the last completed node without re-running all LLM calls.

**Pre-checkpoint phases:** use the graph without persistent checkpoints. The implementation uses `EdtPipelineBStateSerializer` for in-memory state cloning because the project DTOs are not Java-`Serializable`.
**Phase 5:** Implement a `MongoCheckpointSaver` backed by the existing MongoDB connection to persist checkpoints between JVM restarts, enabling true resume-on-crash.

The checkpoint is keyed by `requestUuid` (passed as `threadId` in `RunnableConfig`):

```java
RunnableConfig config = RunnableConfig.builder()
        .threadId(request.getRequestUuid())
        .build();

boolean resume = checkpointSaver.get(config).isPresent();
CompiledGraph<EdtPipelineBState> graph = graphFactory.build(checkpointSaver);
GraphInput input = resume ? GraphInput.resume(initialInput) : GraphInput.args(initialInput);

EdtPipelineBState finalState = graph.invoke(input, config)
        .orElseThrow(() -> new EdtPipelineBGraphException("Pipeline B graph completed without final state"));
```

Implementation note: LangGraph4j saver wiring is version-sensitive. For the current `1.8.x` line, verify the exact API before coding; recent examples wire savers through `CompileConfig.builder().checkpointSaver(...)` at compile time.

Phase 5 implementation decision: checkpoints are stored in MongoDB collection `edt_pipeline_b_graph_checkpoints`, keyed by `requestUuid` as LangGraph4j `threadId`. Each checkpoint entry stores `checkpointId`, `nodeId`, `nextNodeId`, and a JSON state payload produced by `EdtPipelineBStateSerializer` with type metadata for project DTO round-tripping. `EdtPipelineBGraphService` checks for an existing checkpoint before invoking the graph, marks the latest run `RUNNING` at stage `GRAPH_RESUME`, compiles the graph with `CompileConfig.builder().checkpointSaver(...)`, and invokes it with `GraphInput.resume(initialInput)` so LangGraph4j continues from the saved `nextNodeId`.

Checkpointing does not replace idempotency. Every node that writes to MongoDB must be safe to re-run after a retry/resume:

- `PrepareDocumentsNode` must skip documents with an existing `documentPreparationByDomain`.
- `AggregateDomainsNode` must avoid duplicate `plannerRunUuids` entries for the same plan UUID.
- `MergeGenerationPlanNode` should save one plan per graph run UUID and should not create a second unrelated plan when resuming the same `requestUuid`.
- `PersistTwinNode` is intentionally last because it deletes/replaces the organization EDT; do not checkpoint after deletion and before save unless the operation is redesigned as atomic enough for the chosen persistence model.

---

## 9. Existing Classes — What Changes and What Stays

| Class | Action | Notes |
|---|---|---|
| `EdtPipelineBTwinGenerationService` | **Keep** (behind feature flag) | Legacy path until graph is validated |
| `PreparationAgentsGate` | **Keep** | Still used by legacy path; `PrepareDocumentsNode` wraps `PreprationAgent` directly |
| `PlanningAgentsGate` | **Keep** | Legacy path only |
| `FinalizationAgentsGate` | **Keep** | Legacy path only |
| `PreprationAgent` | **No change** | Reused as-is inside `PrepareDocumentsNode` |
| `EdtPlannerAgent` | **No change** | Legacy path only; its logic is split across the new domain planner nodes |
| `IdentityDomainPlanner` | **No change** | Wrapped by `PlanIdentityNode` |
| `FinanceDomainPlanner` | **No change** | Wrapped by `PlanFinanceNode` |
| `ComplianceDomainPlanner` | **No change** | Wrapped by `PlanComplianceNode` |
| `BusinessDomainPlanner` | **No change** | Wrapped by `PlanBusinessNode` |
| `BusinessDomainPlanExecutor` | **No change** | Wrapped by `PlanBusinessNode` |
| `OperationsDomainPlanner` | **Guarded** | Phase 1 graph uses fail-fast `PlanOperationsNode`; implement planner before enabling operations-domain EDT generation |
| `EdtFinalizationAgent` | **No change** | Legacy path only; logic split across finalizer nodes |
| `IdentityDomainProcessor` | **No change** | Wrapped by `FinalizeIdentityNode` |
| `FinancialDomainProcessor` | **No change** | Wrapped by `FinalizeFinancialNode` |
| `ComplianceDomainProcessor` | **No change** | Wrapped by `FinalizeComplianceNode` |
| `BusinessDomainProcessor` | **No change** | Wrapped by `FinalizeBusinessNode`; may call `BusinessDomainFusionAgent` |
| `BusinessDomainFusionAgent` | **No change** | Reused through `BusinessDomainProcessor`; count as finalization LLM work |
| `EdtRequestFacadeProcessor` | **Minor change** | Feature flag branch added |

---

## 10. New Package Structure

```
com.velia.dto.edt.pipelineb.graph
    EdtPipelineBState.java           (extends AgentState)

com.velia.components.edt.pipelineb.graph
    EdtPipelineBGraphFactory.java
    nodes/
        IntakeNode.java
        PrepareDocumentsNode.java
        AggregateDomainsNode.java
        PlanIdentityNode.java
        PlanFinanceNode.java
        PlanComplianceNode.java
        PlanBusinessNode.java
        PlanOperationsNode.java
        MergeGenerationPlanNode.java
        InitTwinNode.java
        FinalizeIdentityNode.java
        FinalizeFinancialNode.java
        FinalizeComplianceNode.java
        FinalizeBusinessNode.java
        MergeTwinNode.java
        PersistTwinNode.java

com.velia.services.edt
    EdtPipelineBGraphService.java
```

---

## 11. Development Phases

### Phase 1 — Foundation and Sequential Graph (functional parity)

**Goal:** graph behaves identically to the current pipeline; no parallel execution yet.

1. Resolve Phase 1 blockers:
   - choose the operations-domain policy from section 4.4;
   - choose whether graph nodes are singleton stateless components or prototype beans resolved through `ObjectProvider`;
   - verify the exact LangGraph4j Maven coordinates and compatibility with the current LangChain4j `1.13.0` dependencies before editing `pom.xml`.
2. Add `langgraph4j-bom` and `langgraph4j-core` to `pom.xml` only after verifying the latest Maven Central version and artifact names. Add LangChain4j integration modules only if the implementation actually uses LangGraph4j-provided LangChain4j adapters.
3. Create `EdtPipelineBState` with full schema and typed accessors. Unit-test channel reducers.
4. Implement all node classes (sequential edges). Wrap existing agents/planners/processors — do not change their logic except for explicitly documented graph failure handling.
5. Implement `EdtPipelineBGraphFactory` (sequential chain as shown in §5).
6. Implement `EdtPipelineBGraphService` with graph timeout from configuration and failure handling for timeout, interruption, and execution failures.
7. Add feature flag branch in `EdtRequestFacadeProcessor`.
8. Integration test: end-to-end graph run with a representative set of organization documents. Compare `EnterpriseDigitalTwinDto`, `EdtGenerationPlanDto`, document planner metadata, and `EdtGenerationRunDto` output against the legacy pipeline for the same input.
9. Quality gate: identical EDT output for the same input, `EdtGenerationPlanDto` has exactly one plan per present domain, `plannerRunUuids` are not duplicated, and `EdtGenerationRunDto` ends as `COMPLETED`.

### Phase 2 — Parallel Document Preparation

**Goal:** prepare all documents concurrently to reduce wall-clock time.

1. Implement `ParallelPrepareDocumentsNode`: fan-out over `rawDocuments` using `CompletableFuture.allOf(...)` and the `VeliaNodesRequestQueue` pool. Each task calls `PreprationAgent.prepare(doc)` and returns `List.of(doc)` to be appended.
2. Switch `prepareDocuments` node in `EdtPipelineBGraphFactory` to the parallel implementation (feature sub-flag or simple replacement).
3. Verify `Channels.appender` correctness: the merged `preparedDocuments` list must contain all N documents regardless of completion order.
4. Restore deterministic document ordering before `aggregateDomains` using the original `rawDocuments` order or an explicit UUID sort.
5. Benchmark latency vs. sequential Phase 1 with a real organization corpus.
6. Quality gate: same EDT output as Phase 1; no race conditions on the queue; no nondeterministic plan/domain ordering.

Phase 2 implementation decision: use the simple replacement path. `EdtPipelineBGraphFactory` keeps the graph edge name `prepareDocuments`, but resolves `ParallelPrepareDocumentsNode`. Deterministic ordering uses the original `rawDocuments` order.

### Phase 3 — Parallel Domain Planning

**Goal:** plan all 5 domains concurrently using LangGraph4j parallel branches.

1. Replace the sequential planner chain with parallel edges:
   ```java
   .addEdge("aggregateDomains", "planIdentity")
   .addEdge("aggregateDomains", "planFinance")
   .addEdge("aggregateDomains", "planCompliance")
   .addEdge("aggregateDomains", "planBusiness")
   .addEdge("aggregateDomains", "planOperations")
   // all five converge to:
   .addEdge("planIdentity",   "mergeGenerationPlan")
   .addEdge("planFinance",    "mergeGenerationPlan")
   .addEdge("planCompliance", "mergeGenerationPlan")
   .addEdge("planBusiness",   "mergeGenerationPlan")
   .addEdge("planOperations", "mergeGenerationPlan")
   ```
2. `mergeGenerationPlan` collects `plannedDomainPlans` (accumulated via `appender`), deduplicates by domain, and assembles `EdtGenerationPlanDto`.
3. Quality gate: `domainPlans` list has exactly one entry per domain present in the documents.

Phase 3 implementation decision: LangGraph4j `1.8.x` creates an internal parallel node when one source has multiple targets, but synchronous `node_async(...)` actions complete immediately and would still run serially. Planner nodes therefore use a dedicated virtual-thread async wrapper while preserving the LangGraph4j fan-out/fan-in edge model. `planOperations` remains part of the fan-out and fails fast if an operations shell exists; other already-started branches may consume rule/LLM work before the graph failure propagates, but no generation plan is persisted before `mergeGenerationPlan`.

### Phase 4 — Parallel Finalization Redesign

**Goal:** make domain finalization parallel without sharing a mutable `EnterpriseDigitalTwinDto`.

1. Introduce immutable domain-slice outputs for identity, finance, compliance, and business finalizers.
2. Change finalizer nodes to return slices instead of mutating a shared EDT instance.
3. Treat the business slice as LLM-capable because it may call `BusinessDomainFusionAgent`; include queue pressure and timeout tests.
4. Update `MergeTwinNode` to compose the final `EnterpriseDigitalTwinDto` from slices plus document metadata.
5. Quality gate: same EDT output as Phase 3; no shared mutable state across finalizer branches.

Phase 4 implementation decision: finalizer nodes create a local working `EnterpriseDigitalTwinDto`, delegate to the existing domain processor, then return an immutable `EdtDomainFinalizationSliceDto` through the `domainFinalizationSlices` appender channel. `InitTwinNode` still creates the base twin with organization/source document metadata. `MergeTwinNode` is the only node that applies finalization slices to the final EDT, preserving one writer for the shared aggregate. Finalizer graph edges fan out from `initTwin` and converge on `mergeTwin` using the same virtual-thread async node wrapper introduced in Phase 3.

### Phase 5 — Checkpoint Persistence

**Goal:** enable resume-on-crash using MongoDB-backed checkpoints.

1. Implement `MongoCheckpointSaver` (or use `langgraph4j-postgres-saver` if PostgreSQL is available).
2. Thread `requestUuid` as `threadId` in `RunnableConfig`.
3. In `EdtPipelineBGraphService`, detect if a checkpoint exists for this `requestUuid`. If so, invoke the graph with `GraphInput.resume(initialInput)` so it resumes from the last completed node — prepared documents and domain plans are already in state and are not re-computed.
4. Update `EdtGenerationRunDto` logic to handle resume (do not reset to QUEUED if a checkpoint exists).
5. Quality gate: simulate a JVM crash after `prepareDocuments`; restart; verify that no new LLM calls are made and the EDT is still produced correctly.

Phase 5 implementation decision: use the project MongoDB connection, not PostgreSQL, for checkpoint persistence. `MongoCheckpointSaverTest` verifies checkpoint persistence, release, and typed DTO state round-trip. `EdtPipelineBGraphServiceTest` uses a real LangGraph4j compiled graph with a checkpoint whose `nextNodeId` bypasses a failing start node, proving that the service uses resume semantics instead of restarting the graph from `START`.

---

## 12. Quality Gates (per `AGENT_CLASS_STRUCTURE_GUIDELINES.md`)

All new node classes must satisfy:

- [ ] Nodes use one Spring lifecycle pattern consistently: stateless singleton `@Component`s, or `@Component @Scope("prototype")` resolved via `ObjectProvider` at graph-build time.
- [ ] `AgentRuntimeEventPublisher` started / running / finished events in nodes that directly call LLM work; if a node only delegates to an existing agent, verify the wrapped agent already emits lifecycle telemetry.
- [ ] Single `instanceUuid` correlating logs and telemetry per direct node execution where telemetry is emitted.
- [ ] `try/finally` for Ollama node queue in nodes that call LLM (delegated to the wrapped agent — nodes themselves may not need this if they only delegate).
- [ ] Node method returns `Map<String, Object>` keyed exactly to `EdtPipelineBState.SCHEMA`.
- [ ] Graph service marks `EdtGenerationRunDto` as `FAILED` for timeout, interruption, and node execution failures.
- [ ] `FinalizeBusinessNode` is tested as an LLM-capable finalization path because it can reach `BusinessDomainFusionAgent`.
- [ ] Operations-domain behavior is explicitly tested according to the chosen policy.
- [ ] Parallel preparation restores deterministic document ordering before domain aggregation.
- [ ] Mongo side effects are idempotent across retry/resume, especially `plannerRunUuids` and generation plan persistence.
- [ ] Unit tests per node: mock dependencies, verify returned state map keys and values.
- [ ] Integration test: full graph run → compare EDT against legacy pipeline output.
- [ ] `EdtPipelineBState` schema unit test: verify appender channels accumulate, default channels overwrite, and final domain plan fan-in rejects duplicates.

---

## 13. Open Questions / Decisions Needed

| # | Question | Impact |
|---|---|---|
| 1 | Resolved for Phase 2: use `CompletableFuture` fan-out inside a single `ParallelPrepareDocumentsNode`. | Architecture complexity |
| 2 | Resolved for Phase 5: use MongoDB via `MongoCheckpointSaver` and the existing project Mongo connection. | Infrastructure |
| 3 | Should `EdtGenerationRunDto` be removed from MongoDB in favour of LangGraph4j checkpoints as the single source of truth for run lifecycle? | Operational change |
| 4 | Enable Studio visualization in dev from Phase 1, or wait until the graph is stable? | Dev experience |
| 5 | Resolved for Phase 1: operations documents use fail-fast behavior until `OperationsDomainPlanner` is implemented. | Functional correctness |
| 6 | Resolved for Phase 1: graph nodes are prototype beans resolved per graph build with `ObjectProvider`. | Spring lifecycle correctness |
| 7 | Should Phase 1 reproduce legacy swallowed exceptions exactly, or adopt fail-fast graph behavior immediately? | Migration risk |
| 8 | Resolved for Phase 2: preserve the original `rawDocuments` order before `aggregateDomains`. | Output reproducibility |
| 9 | Resolved for Phase 3: planner fan-out uses LangGraph4j parallel edges plus virtual-thread async node actions. | Runtime concurrency |
| 10 | Resolved for Phase 4: finalization fan-out returns immutable domain slices and merges them centrally in `MergeTwinNode`. | Mutable shared-state safety |
