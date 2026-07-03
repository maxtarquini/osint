package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
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
public class IntelligenceAssessmentDto {

    @JsonProperty("geopolitical_area")
    private String geopoliticalArea;

    @JsonProperty("strategic_actors")
    @Builder.Default
    private List<String> strategicActors = new ArrayList<>();

    @JsonProperty("operational_actors")
    @Builder.Default
    private List<String> operationalActors = new ArrayList<>();

    @JsonProperty("alliances")
    @Builder.Default
    private List<String> alliances = new ArrayList<>();

    @JsonProperty("adversaries")
    @Builder.Default
    private List<String> adversaries = new ArrayList<>();

    @JsonProperty("objectives")
    @Builder.Default
    private List<String> objectives = new ArrayList<>();

    @JsonProperty("capabilities")
    @Builder.Default
    private List<String> capabilities = new ArrayList<>();

    @JsonProperty("implications")
    @Builder.Default
    private List<String> implications = new ArrayList<>();
}
