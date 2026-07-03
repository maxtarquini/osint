package it.osint.raven.workflow.agent;

import it.osint.raven.dto.article.ArticleDto;
import it.osint.raven.dto.article.MetadataDto;
import it.osint.raven.workflow.StructuredDocument;
import it.osint.raven.workflow.WorkflowContext;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.Optional;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WorkflowAgentTest {

    @Test
    void exposesExpectedDefaultMetadataAndExecutionBehavior() throws Exception {
        WorkflowAgent agent = new MetadataExtractionAgent();
        ArticleDto article = ArticleDto.builder()
                .metadata(MetadataDto.builder().title("Tripoli update").build())
                .build();
        WorkflowContext context = new WorkflowContext()
                .document(article)
                .put("parser", article)
                .put("parser", StructuredDocument.class, article);

        assertEquals("metadata-agent", agent.id());
        assertEquals("Metadata Extraction Agent", agent.name());
        assertEquals(WorkflowAgentType.EXTRACTION, agent.type());
        assertEquals(Set.of(StructuredDocument.class), agent.requires());
        assertEquals(Set.of(MetadataDto.class), agent.produces());
        assertEquals(Map.of(), agent.configuration());
        assertFalse(agent.aiPowered());
        assertTrue(agent.deterministic());
        assertEquals("1.0", agent.version());
        assertEquals(Optional.empty(), agent.modelName());
        assertEquals(Optional.empty(), agent.promptId());
        assertTrue(agent.supports(article));

        WorkflowContext result = agent.execute(context);

        assertSame(context, result);
        assertEquals("Tripoli update", result.require(MetadataDto.class).getTitle());
    }

    @Test
    void llmAgentDeclaresAiPoweredNonDeterministicDefaults() {
        LlmAgent agent = new TestLlmAgent();

        assertTrue(agent.aiPowered());
        assertFalse(agent.deterministic());
        assertEquals(Optional.of("gpt-5"), agent.modelName());
        assertEquals(Optional.of("metadata-prompt"), agent.promptId());
    }

    @Test
    void connectorAgentDefaultsToConnectorType() {
        ConnectorAgent agent = new TestConnectorAgent();

        assertEquals(WorkflowAgentType.CONNECTOR, agent.type());
        assertFalse(agent.supports(null));
    }

    private static final class MetadataExtractionAgent implements DeterministicAgent {

        @Override
        public String id() {
            return "metadata-agent";
        }

        @Override
        public String name() {
            return "Metadata Extraction Agent";
        }

        @Override
        public String description() {
            return "Extracts metadata from supported structured documents.";
        }

        @Override
        public WorkflowAgentType type() {
            return WorkflowAgentType.EXTRACTION;
        }

        @Override
        public Set<Class<?>> requires() {
            return Set.of(StructuredDocument.class);
        }

        @Override
        public Set<Class<?>> produces() {
            return Set.of(MetadataDto.class);
        }

        @Override
        public boolean supports(StructuredDocument document) {
            return document instanceof ArticleDto;
        }

        @Override
        public WorkflowContext execute(WorkflowContext context) {
            ArticleDto article = context.require(ArticleDto.class);
            MetadataDto metadata = MetadataDto.builder()
                    .title(article.getMetadata().getTitle())
                    .build();
            return context
                    .put(id(), metadata)
                    .metric("metadata_agent_outputs", 1);
        }
    }

    private static final class TestLlmAgent implements LlmAgent {

        @Override
        public String id() {
            return "llm-agent";
        }

        @Override
        public String name() {
            return "LLM Agent";
        }

        @Override
        public String description() {
            return "Agent used to verify LLM metadata.";
        }

        @Override
        public WorkflowAgentType type() {
            return WorkflowAgentType.REASONING;
        }

        @Override
        public Set<Class<?>> requires() {
            return Set.of(String.class);
        }

        @Override
        public Set<Class<?>> produces() {
            return Set.of(String.class);
        }

        @Override
        public Optional<String> modelName() {
            return Optional.of("gpt-5");
        }

        @Override
        public Optional<String> promptId() {
            return Optional.of("metadata-prompt");
        }

        @Override
        public WorkflowContext execute(WorkflowContext context) {
            return context;
        }
    }

    private static final class TestConnectorAgent implements ConnectorAgent {

        @Override
        public String id() {
            return "connector-agent";
        }

        @Override
        public String name() {
            return "Connector Agent";
        }

        @Override
        public String description() {
            return "Agent used to verify connector metadata.";
        }

        @Override
        public Set<Class<?>> requires() {
            return Set.of();
        }

        @Override
        public Set<Class<?>> produces() {
            return Set.of(String.class);
        }

        @Override
        public boolean supports(StructuredDocument document) {
            return document != null;
        }

        @Override
        public WorkflowContext execute(WorkflowContext context) {
            return context.put(id(), "external document");
        }
    }
}
