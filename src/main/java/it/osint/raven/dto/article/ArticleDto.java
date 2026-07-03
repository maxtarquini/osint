package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class ArticleDto {

    @JsonProperty("id")
    private UUID id;

    @JsonProperty("raw_document_id")
    private UUID rawDocumentId;

    @JsonProperty("metadata")
    private MetadataDto metadata;

    @JsonProperty("taxonomy")
    private TaxonomyDto taxonomy;

    @JsonProperty("entities")
    @Builder.Default
    private List<EntityDto> entities = new ArrayList<>();

    @JsonProperty("relationships")
    @Builder.Default
    private List<RelationshipDto> relationships = new ArrayList<>();

    @JsonProperty("events")
    @Builder.Default
    private List<EventDto> events = new ArrayList<>();

    @JsonProperty("intelligence_assessment")
    private IntelligenceAssessmentDto intelligenceAssessment;

    @JsonProperty("assessment")
    private AssessmentDto assessment;

    @JsonProperty("embedding")
    private EmbeddingDto embedding;

    @JsonProperty("provenance")
    private ProvenanceDto provenance;

    @JsonProperty("links")
    private LinksDto links;

    @JsonProperty("claims")
    @Builder.Default
    private List<ClaimDto> claims = new ArrayList<>();
}
