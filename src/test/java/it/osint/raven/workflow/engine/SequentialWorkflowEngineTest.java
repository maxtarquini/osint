package it.osint.raven.workflow.engine;

import it.osint.raven.workflow.WorkflowCapability;
import it.osint.raven.workflow.WorkflowContext;
import it.osint.raven.workflow.WorkflowEventType;
import it.osint.raven.workflow.WorkflowNode;
import it.osint.raven.workflow.WorkflowNodeCategory;
import it.osint.raven.workflow.WorkflowStatus;
import it.osint.raven.workflow.compiler.DependencyGraph;
import it.osint.raven.workflow.compiler.ExecutionOrder;
import it.osint.raven.workflow.compiler.ExecutionPlan;
import it.osint.raven.workflow.compiler.ExecutionStage;
import it.osint.raven.workflow.definition.WorkflowDefinition;
import org.junit.jupiter.api.Test;

import java.lang.module.ModuleDescriptor.Version;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SequentialWorkflowEngineTest {

    private static final WorkflowCapability INPUT = WorkflowCapability.produced("input", String.class);
    private static final WorkflowCapability OUTPUT = WorkflowCapability.produced("output", String.class);

    private final SequentialWorkflowEngine engine = new SequentialWorkflowEngine();

    @Test
    void executesPlanNodesInOrderAndRecordsLifecycle() throws Exception {
        List<String> calls = new ArrayList<>();
        RecordingNode first = new RecordingNode("first", Set.of(), Set.of(INPUT), calls)
                .producesValue(INPUT, "ready");
        RecordingNode second = new RecordingNode("second", Set.of(INPUT), Set.of(OUTPUT), calls)
                .producesValue(OUTPUT, "done");

        WorkflowResult result = engine.execute(plan(first, second), new WorkflowContext("test"));

        assertEquals(WorkflowExecutionStatus.SUCCESS, result.status());
        assertEquals(WorkflowStatus.COMPLETED, result.context().getStatus());
        assertEquals(List.of("first", "second"), result.executedNodes());
        assertEquals(List.of(), result.failedNodes());
        assertEquals(List.of(), result.skippedNodes());
        assertEquals(List.of(
                "first:before", "first:execute", "first:after",
                "second:before", "second:execute", "second:after"
        ), calls);
        assertEquals("done", result.context().require(OUTPUT));
        assertTrue(result.context().getEvents().stream()
                .anyMatch(event -> event.type() == WorkflowEventType.WORKFLOW_COMPLETED));
    }

    @Test
    void retriesIdempotentNodeUntilItSucceeds() throws Exception {
        FlakyNode node = new FlakyNode("flaky", 2, true, 3);

        WorkflowResult result = engine.execute(plan(node), new WorkflowContext());

        assertEquals(WorkflowExecutionStatus.SUCCESS, result.status());
        assertEquals(List.of("flaky"), result.executedNodes());
        assertEquals(3, node.attempts);
        assertEquals(2, result.context().getErrors().size());
    }

    @Test
    void doesNotRetryNonIdempotentNode() throws Exception {
        FlakyNode node = new FlakyNode("side-effect", 1, false, 5);

        WorkflowResult result = engine.execute(plan(node), new WorkflowContext());

        assertEquals(WorkflowExecutionStatus.FAILED, result.status());
        assertEquals(List.of("side-effect"), result.failedNodes());
        assertEquals(1, node.attempts);
    }

    @Test
    void skipsNodeWhenRuntimeRequirementsAreMissing() throws Exception {
        RecordingNode missingInputNode = new RecordingNode("consumer", Set.of(INPUT), Set.of(OUTPUT), new ArrayList<>());

        WorkflowResult result = engine.execute(plan(missingInputNode), new WorkflowContext());

        assertEquals(WorkflowExecutionStatus.FAILED, result.status());
        assertEquals(List.of("consumer"), result.skippedNodes());
        assertTrue(result.context().getWarnings().contains("Workflow node skipped: consumer"));
        assertFalse(result.context().contains(OUTPUT));
    }

    @Test
    void marksSlowNodeAsFailedWhenMeasuredExecutionExceedsTimeout() throws Exception {
        SlowNode node = new SlowNode("slow");

        WorkflowResult result = engine.execute(plan(node), new WorkflowContext());

        assertEquals(WorkflowExecutionStatus.FAILED, result.status());
        assertEquals(List.of("slow"), result.failedNodes());
        assertEquals(1, result.context().getErrors().size());
        assertTrue(result.context().getErrors().getFirst().exception().contains("TimeoutException"));
    }

    @Test
    void continuesWithContextReturnedByNodeExecution() throws Exception {
        WorkflowContext replacement = new WorkflowContext("replacement")
                .put("replacement-node", INPUT, "ready");
        ReplacingNode first = new ReplacingNode("replace", replacement);
        RecordingNode second = new RecordingNode("consumer", Set.of(INPUT), Set.of(OUTPUT), new ArrayList<>())
                .producesValue(OUTPUT, "done");

        WorkflowResult result = engine.execute(plan(first, second), new WorkflowContext("initial"));

        assertSame(replacement, result.context());
        assertEquals(WorkflowExecutionStatus.SUCCESS, result.status());
        assertEquals("done", result.context().require(OUTPUT));
    }

    private static ExecutionPlan plan(WorkflowNode... nodes) {
        WorkflowDefinition definition = new WorkflowDefinition(
                "engine-test",
                "Engine Test",
                "Sequential workflow engine test.",
                Version.parse("1.0"),
                List.of(),
                Map.of(),
                Map.of()
        );
        List<WorkflowNode> orderedNodes = List.of(nodes);
        ExecutionStage[] stages = new ExecutionStage[orderedNodes.size()];
        for (int index = 0; index < orderedNodes.size(); index++) {
            WorkflowNode node = orderedNodes.get(index);
            stages[index] = new ExecutionStage(index + 1, node, node.requires(), node.produces());
        }
        return new ExecutionPlan(
                definition,
                stages,
                new DependencyGraph(orderedNodes, List.of()),
                new ExecutionOrder(orderedNodes)
        );
    }

    private static class RecordingNode implements WorkflowNode {

        private final String id;
        private final Set<WorkflowCapability> requires;
        private final Set<WorkflowCapability> produces;
        private final List<String> calls;
        private WorkflowCapability producedCapability;
        private Object producedValue;

        private RecordingNode(
                String id,
                Set<WorkflowCapability> requires,
                Set<WorkflowCapability> produces,
                List<String> calls
        ) {
            this.id = id;
            this.requires = requires;
            this.produces = produces;
            this.calls = calls;
        }

        private RecordingNode producesValue(WorkflowCapability capability, Object value) {
            this.producedCapability = capability;
            this.producedValue = value;
            return this;
        }

        @Override
        public String id() {
            return id;
        }

        @Override
        public String name() {
            return id;
        }

        @Override
        public String description() {
            return "Recording node " + id;
        }

        @Override
        public WorkflowNodeCategory category() {
            return WorkflowNodeCategory.UTILITY;
        }

        @Override
        public Set<WorkflowCapability> requires() {
            return requires;
        }

        @Override
        public Set<WorkflowCapability> produces() {
            return produces;
        }

        @Override
        public void beforeExecute(WorkflowContext context) {
            calls.add(id + ":before");
        }

        @Override
        public WorkflowContext execute(WorkflowContext context) throws Exception {
            calls.add(id + ":execute");
            if (producedCapability != null) {
                context.put(id, producedCapability, producedValue);
            }
            return context;
        }

        @Override
        public void afterExecute(WorkflowContext context) {
            calls.add(id + ":after");
        }
    }

    private static final class FlakyNode extends RecordingNode {

        private final int failuresBeforeSuccess;
        private final boolean idempotent;
        private final int maxRetries;
        private int attempts;

        private FlakyNode(String id, int failuresBeforeSuccess, boolean idempotent, int maxRetries) {
            super(id, Set.of(), Set.of(OUTPUT), new ArrayList<>());
            this.failuresBeforeSuccess = failuresBeforeSuccess;
            this.idempotent = idempotent;
            this.maxRetries = maxRetries;
        }

        @Override
        public WorkflowContext execute(WorkflowContext context) {
            attempts++;
            if (attempts <= failuresBeforeSuccess) {
                throw new IllegalStateException("temporary failure");
            }
            context.put(id(), OUTPUT, "done");
            return context;
        }

        @Override
        public int maxRetries() {
            return maxRetries;
        }

        @Override
        public boolean idempotent() {
            return idempotent;
        }
    }

    private static final class SlowNode extends RecordingNode {

        private SlowNode(String id) {
            super(id, Set.of(), Set.of(OUTPUT), new ArrayList<>());
        }

        @Override
        public WorkflowContext execute(WorkflowContext context) throws InterruptedException {
            Thread.sleep(20);
            return context;
        }

        @Override
        public Duration timeout() {
            return Duration.ofMillis(1);
        }
    }

    private static final class ReplacingNode extends RecordingNode {

        private final WorkflowContext replacement;

        private ReplacingNode(String id, WorkflowContext replacement) {
            super(id, Set.of(), Set.of(INPUT), new ArrayList<>());
            this.replacement = replacement;
        }

        @Override
        public WorkflowContext execute(WorkflowContext context) {
            return replacement;
        }
    }
}
