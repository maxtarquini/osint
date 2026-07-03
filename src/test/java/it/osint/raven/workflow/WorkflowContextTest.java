package it.osint.raven.workflow;

import it.osint.raven.dto.article.ArticleDto;
import it.osint.raven.dto.article.EntityDto;
import it.osint.raven.dto.article.MetadataDto;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class WorkflowContextTest {

    @Test
    void storesAndReadsTypedOutputsWithoutExplicitCasts() {
        MetadataDto metadata = MetadataDto.builder()
                .title("Tripoli update")
                .build();
        WorkflowContext context = new WorkflowContext("article-analysis")
                .put("metadata-agent", metadata);

        assertTrue(context.contains(MetadataDto.class));
        assertSame(metadata, context.require(MetadataDto.class));
        assertEquals("Tripoli update", context.get(MetadataDto.class).orElseThrow().getTitle());

        WorkflowArtifact artifact = context.getArtifact(MetadataDto.class).orElseThrow();
        assertEquals(MetadataDto.class, artifact.type());
        assertEquals("metadata-agent", artifact.producedBy());
        assertNotNull(artifact.id());
        assertNotNull(artifact.producedAt());
    }

    @Test
    void supportsAssignableTypesForStructuredDocumentsAndLists() {
        ArticleDto article = ArticleDto.builder().build();
        List<EntityDto> entities = List.of(EntityDto.builder().name("Italy").build());

        WorkflowContext context = new WorkflowContext()
                .document(article)
                .put("parser", article)
                .put("entity-agent", List.class, entities);

        assertSame(article, context.getDocument());
        assertSame(article, context.require(ArticleDto.class));
        assertInstanceOf(ArticleDto.class, context.require(StructuredDocument.class));
        assertEquals("Italy", ((EntityDto) context.require(List.class).getFirst()).getName());
    }

    @Test
    void supportsNamedCapabilitiesWithSameJavaType() {
        WorkflowCapability entityExtraction = WorkflowCapability.produced("entity-extraction", List.class);
        WorkflowCapability organizationResolution = WorkflowCapability.produced("organization-resolution", List.class);
        List<EntityDto> extractedEntities = List.of(EntityDto.builder().name("Italy").build());
        List<EntityDto> resolvedOrganizations = List.of(EntityDto.builder().name("ACME").build());

        WorkflowContext context = new WorkflowContext()
                .put("entity-extractor", entityExtraction, extractedEntities)
                .put("organization-resolver", organizationResolution, resolvedOrganizations);

        assertTrue(context.contains(entityExtraction));
        assertTrue(context.contains(organizationResolution));
        List<?> requiredExtractedEntities = context.require(entityExtraction);
        List<?> requiredResolvedOrganizations = context.require(organizationResolution);

        assertEquals("Italy", ((EntityDto) requiredExtractedEntities.getFirst()).getName());
        assertEquals("ACME", ((EntityDto) requiredResolvedOrganizations.getFirst()).getName());
        assertEquals("entity-extractor", context.getArtifact(entityExtraction).orElseThrow().producedBy());
        assertEquals("organization-resolver", context.getArtifact(organizationResolution).orElseThrow().producedBy());
    }

    @Test
    void storesCapabilityOutputsByQualifiedNameAndAliases() {
        WorkflowCapability entityExtraction = WorkflowCapability.builder()
                .namespace("osint")
                .id("entity-extraction")
                .description("Extracted named entities")
                .type(List.class)
                .aliases(Set.of("entities", "ner"))
                .build();
        WorkflowCapability entitiesAlias = WorkflowCapability.builder()
                .namespace("osint")
                .id("entities")
                .type(List.class)
                .build();
        List<EntityDto> entities = List.of(EntityDto.builder().name("Italy").build());

        WorkflowContext context = new WorkflowContext()
                .put("entity-extractor", entityExtraction, entities);

        assertTrue(context.contains(entityExtraction));
        assertTrue(context.contains(entitiesAlias));
        assertTrue(context.getCapabilityOutputs().containsKey("osint:entity-extraction@1.0.0"));
        assertTrue(context.getCapabilityOutputs().containsKey("osint:entities@1.0.0"));
        List<?> requiredEntities = context.require(entitiesAlias);
        assertEquals("Italy", ((EntityDto) requiredEntities.getFirst()).getName());
    }

    @Test
    void recordsVariablesMetricsWarningsErrorsEventsAndStatus() {
        WorkflowContext context = new WorkflowContext()
                .status(WorkflowStatus.RUNNING)
                .variable("correlation_id", "abc-123")
                .metric("entities_found", 3)
                .warning("low confidence extraction")
                .error("entity-agent", new IllegalStateException("model unavailable"))
                .event("entity-agent", WorkflowEventType.NODE_COMPLETED, "Entity extraction completed")
                .status(WorkflowStatus.PARTIAL);

        assertEquals(WorkflowStatus.PARTIAL, context.getStatus());
        assertEquals("abc-123", context.getVariables().get("correlation_id"));
        assertEquals(3, context.getMetrics().get("entities_found"));
        assertEquals(List.of("low confidence extraction"), context.getWarnings());
        assertEquals("java.lang.IllegalStateException", context.getErrors().getFirst().exception());
        assertFalse(context.getEvents().isEmpty());
        assertTrue(context.getEvents().stream().anyMatch(event -> event.type() == WorkflowEventType.NODE_COMPLETED));
    }

    @Test
    void requireFailsWhenOutputIsMissing() {
        WorkflowContext context = new WorkflowContext();

        IllegalStateException exception = assertThrows(
                IllegalStateException.class,
                () -> context.require(MetadataDto.class)
        );

        assertTrue(exception.getMessage().contains(MetadataDto.class.getName()));
    }
}
