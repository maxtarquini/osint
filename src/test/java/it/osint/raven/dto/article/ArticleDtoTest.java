package it.osint.raven.dto.article;

import com.fasterxml.jackson.databind.ObjectMapper;
import it.osint.raven.utils.article.ArticleObjectMapper;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ArticleDtoTest {

    private final ObjectMapper objectMapper = ArticleObjectMapper.create();

    @Test
    void initializesCollectionFieldsWithDeterministicDefaults() {
        ArticleDto article = ArticleDto.builder()
                .metadata(MetadataDto.builder().title("Libya talks resume").build())
                .taxonomy(TaxonomyDto.builder().domain("Political Affairs").build())
                .build();

        assertNotNull(article.getEntities());
        assertNotNull(article.getRelationships());
        assertNotNull(article.getEvents());
        assertNotNull(article.getClaims());
        assertTrue(article.getEntities().isEmpty());
        assertTrue(article.getClaims().isEmpty());
        assertNotNull(article.getMetadata().getTags());
        assertNotNull(article.getTaxonomy().getKeywords());
    }

    @Test
    void ignoresUnknownFieldsDuringDeserialization() throws Exception {
        String json = """
                {
                  "id": "4f13ff9c-0257-4df0-9f5b-4a5666af3173",
                  "raw_document_id": "f1399ec1-7a74-40a8-ae57-d750f9d4cd61",
                  "unknown_pipeline_field": "ignored",
                  "metadata": {
                    "title": "Tripoli security update",
                    "ignored_metadata_field": "ignored"
                  }
                }
                """;

        ArticleDto article = objectMapper.readValue(json, ArticleDto.class);

        assertEquals(UUID.fromString("4f13ff9c-0257-4df0-9f5b-4a5666af3173"), article.getId());
        assertEquals(UUID.fromString("f1399ec1-7a74-40a8-ae57-d750f9d4cd61"), article.getRawDocumentId());
        assertEquals("Tripoli security update", article.getMetadata().getTitle());
    }

    @Test
    void serializesArticleContractUsingSnakeCaseJsonProperties() throws Exception {
        ArticleDto article = ArticleDto.builder()
                .rawDocumentId(UUID.fromString("f1399ec1-7a74-40a8-ae57-d750f9d4cd61"))
                .metadata(MetadataDto.builder()
                        .publicationDate(LocalDate.of(2026, 7, 3))
                        .build())
                .taxonomy(TaxonomyDto.builder()
                        .subDomain("Elections")
                        .impactLevel("HIGH")
                        .build())
                .intelligenceAssessment(IntelligenceAssessmentDto.builder()
                        .geopoliticalArea("North Africa")
                        .strategicActors(java.util.List.of("Egypt"))
                        .build())
                .embedding(EmbeddingDto.builder()
                        .embeddingId(UUID.fromString("bc535758-90f1-4334-bb59-1805a5830f07"))
                        .dimensions(3)
                        .vector(new float[]{0.1f, 0.2f, 0.3f})
                        .build())
                .build();

        String json = objectMapper.writeValueAsString(article);

        assertTrue(json.contains("\"raw_document_id\":\"f1399ec1-7a74-40a8-ae57-d750f9d4cd61\""));
        assertTrue(json.contains("\"publication_date\":\"2026-07-03\""));
        assertTrue(json.contains("\"sub_domain\":\"Elections\""));
        assertTrue(json.contains("\"impact_level\":\"HIGH\""));
        assertTrue(json.contains("\"intelligence_assessment\""));
        assertTrue(json.contains("\"geopolitical_area\":\"North Africa\""));
        assertTrue(json.contains("\"strategic_actors\":[\"Egypt\"]"));
        assertTrue(json.contains("\"embedding_id\":\"bc535758-90f1-4334-bb59-1805a5830f07\""));
    }

    @Test
    void representsClaimsWithEvidenceAndEntityReferences() {
        UUID egypt = UUID.randomUUID();
        UUID haftar = UUID.randomUUID();
        EvidenceDto evidence = EvidenceDto.builder()
                .type(EvidenceType.ARTICLE_TEXT)
                .source("Article paragraph 4")
                .excerpt("Egypt supports Haftar, according to the article.")
                .confidence(0.74)
                .build();

        ClaimDto claim = ClaimDto.builder()
                .sourceEntityId(egypt)
                .statement("Egypt supports Haftar")
                .targetEntityIds(java.util.List.of(haftar))
                .type(ClaimType.FACTUAL_ASSERTION)
                .confidence(Confidence.MEDIUM)
                .evidence(java.util.List.of(evidence))
                .build();

        ArticleDto article = ArticleDto.builder()
                .claims(java.util.List.of(claim))
                .build();

        assertEquals(egypt, article.getClaims().getFirst().getSourceEntityId());
        assertEquals(haftar, article.getClaims().getFirst().getTargetEntityIds().getFirst());
        assertEquals(EvidenceType.ARTICLE_TEXT, article.getClaims().getFirst().getEvidence().getFirst().getType());
        assertEquals(Confidence.MEDIUM, article.getClaims().getFirst().getConfidence());
    }
}
