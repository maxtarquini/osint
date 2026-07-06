package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import it.osint.raven.workflow.StructuredDocument;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.mongodb.core.index.CompoundIndex;
import org.springframework.data.mongodb.core.index.CompoundIndexes;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;
import org.springframework.data.mongodb.core.mapping.Field;
import org.springframework.data.mongodb.core.mapping.FieldType;
import org.springframework.data.mongodb.core.mapping.MongoId;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Document(collection = "articles")
@Schema(description = "Structured intelligence article derived from a raw acquired document.")
@CompoundIndexes({
        @CompoundIndex(
                name = "articles_publication_date_idx",
                def = "{ 'metadata.publication_date': -1 }",
                sparse = true
        ),
        @CompoundIndex(
                name = "articles_taxonomy_idx",
                def = "{ 'taxonomy.domain': 1, 'taxonomy.sub_domain': 1, 'taxonomy.event_type': 1 }",
                sparse = true
        ),
        @CompoundIndex(
                name = "articles_entities_idx",
                def = "{ 'entities.normalized_name': 1, 'entities.type': 1 }",
                sparse = true
        ),
        @CompoundIndex(
                name = "articles_events_idx",
                def = "{ 'events.type': 1, 'events.date': 1 }",
                sparse = true
        )
})
public class ArticleDto implements StructuredDocument {

    @JsonProperty("id")
    @MongoId(FieldType.STRING)
    @Schema(description = "Article identifier.", example = "4f13ff9c-0257-4df0-9f5b-4a5666af3173")
    private UUID id;

    @JsonProperty("raw_document_id")
    @Indexed(name = "articles_raw_document_id_unique", unique = true, sparse = true)
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Raw document identifier used as the source for this article.", example = "f1399ec1-7a74-40a8-ae57-d750f9d4cd61")
    private UUID rawDocumentId;

    @JsonProperty("metadata")
    @Schema(description = "Publication metadata extracted from the article.")
    private MetadataDto metadata;

    @JsonProperty("taxonomy")
    @Schema(description = "Domain taxonomy and topic classification.")
    private TaxonomyDto taxonomy;

    @JsonProperty("entities")
    @Schema(description = "Entities mentioned in the article.")
    @Builder.Default
    private List<EntityDto> entities = new ArrayList<>();

    @JsonProperty("relationships")
    @Schema(description = "Relationships inferred between extracted entities.")
    @Builder.Default
    private List<RelationshipDto> relationships = new ArrayList<>();

    @JsonProperty("events")
    @Schema(description = "Events described by the article.")
    @Builder.Default
    private List<EventDto> events = new ArrayList<>();

    @JsonProperty("intelligence_assessment")
    @Schema(description = "Strategic and operational intelligence assessment.")
    private IntelligenceAssessmentDto intelligenceAssessment;

    @JsonProperty("assessment")
    @Schema(description = "Quality, reliability and relevance assessment.")
    private AssessmentDto assessment;

    @JsonProperty("embedding")
    @Schema(description = "Vector embedding metadata and vector payload.")
    private EmbeddingDto embedding;

    @JsonProperty("provenance")
    @Schema(description = "Extraction and parser provenance.")
    private ProvenanceDto provenance;

    @JsonProperty("links")
    @Schema(description = "Links to related articles and events.")
    private LinksDto links;

    @JsonProperty("claims")
    @Schema(description = "Claims extracted from the article with supporting evidence.")
    @Builder.Default
    private List<ClaimDto> claims = new ArrayList<>();
}
