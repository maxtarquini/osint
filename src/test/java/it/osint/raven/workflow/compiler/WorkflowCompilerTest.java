package it.osint.raven.workflow.compiler;

import it.osint.raven.workflow.WorkflowCapability;
import it.osint.raven.workflow.WorkflowContext;
import it.osint.raven.workflow.WorkflowNode;
import it.osint.raven.workflow.WorkflowNodeCategory;
import it.osint.raven.workflow.definition.WorkflowDefinition;
import it.osint.raven.workflow.definition.WorkflowGoal;
import it.osint.raven.workflow.registry.WorkflowRegistry;
import org.junit.jupiter.api.Test;

import java.lang.module.ModuleDescriptor.Version;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WorkflowCompilerTest {

    private static final WorkflowCapability STRUCTURED_DOCUMENT = capability("structured-document");
    private static final WorkflowCapability ENTITIES = capability("entities");
    private static final WorkflowCapability CLAIMS = capability("claims");
    private static final WorkflowCapability ASSESSMENT = capability("assessment");
    private static final WorkflowCapability METADATA = capability("metadata");

    private final WorkflowCompiler compiler = new WorkflowCompiler();

    @Test
    void compilesGoalIntoFullDependencyExecutionPlan() {
        TestNode parser = new TestNode("parser", Set.of(), Set.of(STRUCTURED_DOCUMENT));
        TestNode entity = new TestNode("entity", Set.of(STRUCTURED_DOCUMENT), Set.of(ENTITIES));
        TestNode claims = new TestNode("claims", Set.of(ENTITIES), Set.of(CLAIMS));
        TestNode assessment = new TestNode("assessment", Set.of(CLAIMS), Set.of(ASSESSMENT));
        WorkflowDefinition definition = definition(goal(ASSESSMENT));
        WorkflowRegistry registry = WorkflowRegistry.create()
                .registerNode(assessment)
                .registerNode(claims)
                .registerNode(entity)
                .registerNode(parser);

        ExecutionPlan plan = compiler.compile(definition, registry);

        assertSame(definition, plan.definition());
        assertEquals(List.of("parser", "entity", "claims", "assessment"), plan.executionOrder().nodeIds());
        assertEquals(List.of("assessment", "claims", "entity", "parser"), plan.dependencyGraph().nodes().stream()
                .map(WorkflowNode::id)
                .toList());
        assertEquals(3, plan.dependencyGraph().edges().size());
        assertArrayEquals(new String[]{"parser", "entity", "claims", "assessment"}, List.of(plan.stages()).stream()
                .map(stage -> stage.node().id())
                .toArray(String[]::new));
        assertEquals(1, plan.stages()[0].index());
        assertEquals(4, plan.stages()[3].index());
    }

    @Test
    void compilesMultipleGoalsAndDeduplicatesSharedDependencies() {
        TestNode parser = new TestNode("parser", Set.of(), Set.of(STRUCTURED_DOCUMENT));
        TestNode metadata = new TestNode("metadata", Set.of(STRUCTURED_DOCUMENT), Set.of(METADATA));
        TestNode entity = new TestNode("entity", Set.of(STRUCTURED_DOCUMENT), Set.of(ENTITIES));
        WorkflowDefinition definition = definition(goal(METADATA), goal(ENTITIES));
        WorkflowRegistry registry = WorkflowRegistry.create()
                .registerNode(entity)
                .registerNode(metadata)
                .registerNode(parser);

        ExecutionPlan plan = compiler.compile(definition, registry);

        assertEquals(List.of("parser", "metadata", "entity"), plan.executionOrder().nodeIds());
        assertEquals(3, plan.dependencyGraph().nodes().size());
        assertEquals(2, plan.dependencyGraph().edges().size());
    }

    @Test
    void throwsMissingCapabilityWhenNoProducerExists() {
        WorkflowDefinition definition = definition(goal(ASSESSMENT));
        WorkflowRegistry registry = WorkflowRegistry.create();

        MissingCapabilityException exception = assertThrows(
                MissingCapabilityException.class,
                () -> compiler.compile(definition, registry)
        );

        assertEquals(ASSESSMENT, exception.capability());
    }

    @Test
    void throwsAmbiguousCapabilityWhenMultipleProducersExist() {
        TestNode first = new TestNode("metadata-a", Set.of(), Set.of(METADATA));
        TestNode second = new TestNode("metadata-b", Set.of(), Set.of(METADATA));
        WorkflowDefinition definition = definition(goal(METADATA));
        WorkflowRegistry registry = WorkflowRegistry.create()
                .registerNode(first)
                .registerNode(second);

        AmbiguousCapabilityException exception = assertThrows(
                AmbiguousCapabilityException.class,
                () -> compiler.compile(definition, registry)
        );

        assertEquals(METADATA, exception.capability());
        assertEquals(List.of(first, second), exception.candidates());
    }

    @Test
    void throwsCircularDependencyWhenSelectedNodesContainCycle() {
        WorkflowCapability a = capability("a");
        WorkflowCapability b = capability("b");
        TestNode nodeA = new TestNode("node-a", Set.of(b), Set.of(a));
        TestNode nodeB = new TestNode("node-b", Set.of(a), Set.of(b));
        WorkflowDefinition definition = definition(goal(a));
        WorkflowRegistry registry = WorkflowRegistry.create()
                .registerNode(nodeA)
                .registerNode(nodeB);

        CircularDependencyException exception = assertThrows(
                CircularDependencyException.class,
                () -> compiler.compile(definition, registry)
        );

        assertTrue(exception.nodeIds().contains("node-a"));
        assertTrue(exception.nodeIds().contains("node-b"));
    }

    @Test
    void executionPlanDefensivelyCopiesStagesArray() {
        TestNode parser = new TestNode("parser", Set.of(), Set.of(STRUCTURED_DOCUMENT));
        WorkflowDefinition definition = definition(goal(STRUCTURED_DOCUMENT));
        WorkflowRegistry registry = WorkflowRegistry.create().registerNode(parser);

        ExecutionPlan plan = compiler.compile(definition, registry);
        ExecutionStage[] stages = plan.stages();
        stages[0] = null;

        assertEquals("parser", plan.stages()[0].node().id());
    }

    private static WorkflowDefinition definition(WorkflowGoal... goals) {
        return new WorkflowDefinition(
                "test-workflow",
                "Test Workflow",
                "Workflow compiler test.",
                Version.parse("1.0"),
                List.of(goals),
                Map.of(),
                Map.of()
        );
    }

    private static WorkflowGoal goal(WorkflowCapability capability) {
        return WorkflowGoal.of(capability, true, 100);
    }

    private static WorkflowCapability capability(String id) {
        return WorkflowCapability.builder()
                .namespace("core")
                .id(id)
                .type(Object.class)
                .build();
    }

    private record TestNode(
            String id,
            Set<WorkflowCapability> requires,
            Set<WorkflowCapability> produces
    ) implements WorkflowNode {

        @Override
        public String name() {
            return id;
        }

        @Override
        public String description() {
            return "Test node " + id;
        }

        @Override
        public WorkflowNodeCategory category() {
            return WorkflowNodeCategory.UTILITY;
        }

        @Override
        public WorkflowContext execute(WorkflowContext context) {
            return context;
        }
    }
}
