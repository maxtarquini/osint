package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class AssessmentDto {

    @JsonProperty("reliability")
    private double reliability;

    @JsonProperty("confidence")
    private double confidence;

    @JsonProperty("relevance")
    private double relevance;

    @JsonProperty("duplicate")
    private boolean duplicate;

    @JsonProperty("propaganda")
    private boolean propaganda;
}
