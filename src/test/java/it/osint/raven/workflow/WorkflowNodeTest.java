package it.osint.raven.workflow;

import it.osint.raven.dto.article.EntityDto;
import it.osint.raven.dto.article.MetadataDto;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.Collections;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WorkflowNodeTest {

    private static final WorkflowCapability METADATA =
            WorkflowCapability.required("metadata-extraction", MetadataDto.class);
    private static final WorkflowCapability ENTITY =
            WorkflowCapability.required("entity-extraction", EntityDto.class);
    private static final WorkflowCapability SUMMARY =
            WorkflowCapability.produced("summary", String.class);

    @Test
    void canExecuteChecksDeclaredRequirementsAgainstContextArtifacts() {
        WorkflowNode node = new TestNode(
                Set.of(METADATA, ENTITY),
                Set.of(SUMMARY)
        );
        WorkflowContext context = new WorkflowContext()
                .put("metadata-extractor", METADATA, MetadataDto.builder().title("Tripoli update").build());

        assertFalse(node.canExecute(context));

        context.put("entity-extractor", ENTITY, EntityDto.builder().name("Italy").build());

        assertTrue(node.canExecute(context));
    }

    @Test
    void canExecuteSupportsNodesWithoutRequirements() {
        WorkflowNode node = new TestNode(Collections.emptySet(), Set.of(METADATA));

        assertTrue(node.canExecute(new WorkflowContext()));
    }

    @Test
    void exposesExpectedDefaultConfigurationAndExecutionPolicies() throws Exception {
        WorkflowNode node = new TestNode(Set.of(METADATA), Set.of(ENTITY));
        WorkflowContext context = new WorkflowContext();

        assertEquals(Map.of(), node.configuration());
        assertEquals(Duration.ofMinutes(5), node.timeout());
        assertEquals(0, node.maxRetries());
        assertTrue(node.parallelizable());
        assertTrue(node.idempotent());
        assertEquals(100, node.priority());
        assertThrows(NullPointerException.class, () -> node.canExecute(null));
        assertSame(context, node.execute(context));
    }

    private record TestNode(
            Set<WorkflowCapability> requires,
            Set<WorkflowCapability> produces
    ) implements WorkflowNode {

        @Override
        public String id() {
            return "test-node";
        }

        @Override
        public String name() {
            return "Test Node";
        }

        @Override
        public String description() {
            return "Node used to verify the workflow node contract.";
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
