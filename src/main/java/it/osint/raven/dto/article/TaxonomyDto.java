package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Domain taxonomy assigned to a structured article.")
public class TaxonomyDto {

    @JsonProperty("domain")
    @Schema(description = "High-level intelligence domain.", example = "Political Affairs")
    private String domain;

    @JsonProperty("sub_domain")
    @Schema(description = "Domain-specific subcategory.", example = "Elections")
    private String subDomain;

    @JsonProperty("event_type")
    @Schema(description = "Primary event type.", example = "diplomatic_meeting")
    private String eventType;

    @JsonProperty("sector")
    @Schema(description = "Relevant sector.", example = "Government")
    private String sector;

    @JsonProperty("impact_level")
    @Schema(description = "Operational impact level.", example = "HIGH")
    private String impactLevel;

    @JsonProperty("topics")
    @Schema(description = "Topic labels assigned to the article.")
    @Builder.Default
    private List<String> topics = new ArrayList<>();

    @JsonProperty("keywords")
    @Schema(description = "Keyword labels assigned to the article.")
    @Builder.Default
    private List<String> keywords = new ArrayList<>();
}
