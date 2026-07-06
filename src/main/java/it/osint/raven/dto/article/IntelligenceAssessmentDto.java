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
@Schema(description = "Strategic and operational intelligence assessment extracted from an article.")
public class IntelligenceAssessmentDto {

    @JsonProperty("geopolitical_area")
    @Schema(description = "Relevant geopolitical area.", example = "North Africa")
    private String geopoliticalArea;

    @JsonProperty("strategic_actors")
    @Schema(description = "Strategic actors mentioned or inferred.")
    @Builder.Default
    private List<String> strategicActors = new ArrayList<>();

    @JsonProperty("operational_actors")
    @Schema(description = "Operational actors mentioned or inferred.")
    @Builder.Default
    private List<String> operationalActors = new ArrayList<>();

    @JsonProperty("alliances")
    @Schema(description = "Relevant alliances described by the article.")
    @Builder.Default
    private List<String> alliances = new ArrayList<>();

    @JsonProperty("adversaries")
    @Schema(description = "Relevant adversarial relationships described by the article.")
    @Builder.Default
    private List<String> adversaries = new ArrayList<>();

    @JsonProperty("objectives")
    @Schema(description = "Stated or inferred actor objectives.")
    @Builder.Default
    private List<String> objectives = new ArrayList<>();

    @JsonProperty("capabilities")
    @Schema(description = "Capabilities mentioned or inferred.")
    @Builder.Default
    private List<String> capabilities = new ArrayList<>();

    @JsonProperty("implications")
    @Schema(description = "Operational or strategic implications.")
    @Builder.Default
    private List<String> implications = new ArrayList<>();
}
