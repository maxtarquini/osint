package it.osint.raven.workflow.registry;

import it.osint.raven.dto.article.EntityDto;
import it.osint.raven.dto.article.MetadataDto;
import it.osint.raven.workflow.StructuredDocument;
import it.osint.raven.workflow.WorkflowCapability;
import it.osint.raven.workflow.WorkflowContext;
import it.osint.raven.workflow.WorkflowNode;
import it.osint.raven.workflow.WorkflowNodeCategory;
import it.osint.raven.workflow.agent.WorkflowAgent;
import it.osint.raven.workflow.agent.WorkflowAgentType;
import org.junit.jupiter.api.Test;

import java.lang.module.ModuleDescriptor.Version;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WorkflowRegistryTest {

    private static final WorkflowCapability STRUCTURED_DOCUMENT = WorkflowCapability.builder()
            .namespace("core")
            .id("structured-document")
            .description("Parsed structured document")
            .type(StructuredDocument.class)
            .required(true)
            .build();

    private static final WorkflowCapability METADATA = WorkflowCapability.builder()
            .namespace("osint")
            .id("metadata")
            .description("Extracted metadata")
            .type(MetadataDto.class)
            .aliases(Set.of("metadata-extraction"))
            .build();

    private static final WorkflowCapability ENTITY_EXTRACTION = WorkflowCapability.builder()
            .namespace("osint")
            .id("entity-extraction")
            .description("Extracted entities")
            .type(List.class)
            .aliases(Set.of("entities", "ner"))
            .build();

    @Test
    void registersAndFindsNodesAndAgentsById() {
        WorkflowNode node = new TestNode("metadata-node", Set.of(STRUCTURED_DOCUMENT), Set.of(METADATA));
        WorkflowAgent agent = new TestAgent("metadata-agent", Set.of(StructuredDocument.class), Set.of(MetadataDto.class));

        WorkflowRegistry registry = WorkflowRegistry.create()
                .registerNode(node)
                .registerAgent(agent);

        assertSame(node, registry.findNode("metadata-node").orElseThrow());
        assertSame(agent, registry.findAgent("metadata-agent").orElseThrow());
        assertEquals(List.of(node), registry.nodes());
        assertEquals(List.of(agent), registry.agents());
        assertTrue(registry.findNode("missing").isEmpty());
        assertTrue(registry.findAgent("missing").isEmpty());
    }

    @Test
    void rejectsDuplicateNodeAndAgentIds() {
        WorkflowNode firstNode = new TestNode("duplicate-node", Set.of(), Set.of(METADATA));
        WorkflowNode secondNode = new TestNode("duplicate-node", Set.of(), Set.of(ENTITY_EXTRACTION));
        WorkflowAgent firstAgent = new TestAgent("duplicate-agent", Set.of(), Set.of(String.class));
        WorkflowAgent secondAgent = new TestAgent("duplicate-agent", Set.of(), Set.of(Integer.class));

        WorkflowRegistry registry = WorkflowRegistry.create()
                .registerNode(firstNode)
                .registerAgent(firstAgent);

        assertThrows(IllegalArgumentException.class, () -> registry.registerNode(secondNode));
        assertThrows(IllegalArgumentException.class, () -> registry.registerAgent(secondAgent));
    }

    @Test
    void findsNodesProducingAndRequiringCapabilitiesByNominalMatch() {
        WorkflowNode metadataNode = new TestNode("metadata-node", Set.of(STRUCTURED_DOCUMENT), Set.of(METADATA));
        WorkflowNode entityNode = new TestNode("entity-node", Set.of(STRUCTURED_DOCUMENT, METADATA), Set.of(ENTITY_EXTRACTION));
        WorkflowCapability metadataAlias = WorkflowCapability.builder()
                .namespace("osint")
                .id("metadata-extraction")
                .type(MetadataDto.class)
                .build();

        WorkflowRegistry registry = WorkflowRegistry.create()
                .registerNode(metadataNode)
                .registerNode(entityNode);

        assertEquals(List.of(metadataNode), registry.findNodesProducing(metadataAlias));
        assertEquals(List.of(metadataNode, entityNode), registry.findNodesRequiring(STRUCTURED_DOCUMENT));
        assertEquals(List.of(entityNode), registry.findNodesProducing(ENTITY_EXTRACTION));
    }

    @Test
    void capabilityLookupIgnoresJavaTypeButRespectsNamespaceAndVersion() {
        WorkflowNode entityNode = new TestNode("entity-node", Set.of(), Set.of(ENTITY_EXTRACTION));
        WorkflowCapability sameCapabilityDifferentType = WorkflowCapability.builder()
                .namespace("osint")
                .id("entity-extraction")
                .type(EntityDto.class)
                .build();
        WorkflowCapability differentNamespace = WorkflowCapability.builder()
                .namespace("graph")
                .id("entity-extraction")
                .type(List.class)
                .build();
        WorkflowCapability differentVersion = WorkflowCapability.builder()
                .namespace("osint")
                .id("entity-extraction")
                .type(List.class)
                .version(Version.parse("2.0.0"))
                .build();

        WorkflowRegistry registry = WorkflowRegistry.create().registerNode(entityNode);

        assertEquals(List.of(entityNode), registry.findNodesProducing(sameCapabilityDifferentType));
        assertTrue(registry.findNodesProducing(differentNamespace).isEmpty());
        assertTrue(registry.findNodesProducing(differentVersion).isEmpty());
    }

    @Test
    void returnsImmutableSnapshots() {
        WorkflowNode node = new TestNode("metadata-node", Set.of(), Set.of(METADATA));
        WorkflowAgent agent = new TestAgent("metadata-agent", Set.of(), Set.of(MetadataDto.class));

        WorkflowRegistry registry = WorkflowRegistry.create()
                .registerNode(node)
                .registerAgent(agent);

        List<WorkflowNode> nodes = registry.nodes();
        List<WorkflowAgent> agents = registry.agents();

        assertThrows(UnsupportedOperationException.class, () -> nodes.add(node));
        assertThrows(UnsupportedOperationException.class, () -> agents.add(agent));
    }

    @Test
    void serviceLoaderDiscoveryReturnsARegistry() {
        WorkflowRegistry registry = WorkflowRegistry.load(WorkflowRegistryTest.class.getClassLoader());

        assertTrue(registry.nodes().isEmpty());
        assertTrue(registry.agents().isEmpty());
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
            return "Test workflow node.";
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

    private record TestAgent(
            String id,
            Set<Class<?>> requires,
            Set<Class<?>> produces
    ) implements WorkflowAgent {

        @Override
        public String name() {
            return id;
        }

        @Override
        public String description() {
            return "Test workflow agent.";
        }

        @Override
        public WorkflowAgentType type() {
            return WorkflowAgentType.UTILITY;
        }

        @Override
        public WorkflowContext execute(WorkflowContext context) {
            return context;
        }
    }
}
