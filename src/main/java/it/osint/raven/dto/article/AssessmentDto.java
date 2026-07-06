package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Article quality and trustworthiness assessment scores.")
public class AssessmentDto {

    @JsonProperty("reliability")
    @Schema(description = "Estimated source/content reliability score from 0.0 to 1.0.", example = "0.82")
    private double reliability;

    @JsonProperty("confidence")
    @Schema(description = "Overall extraction confidence score from 0.0 to 1.0.", example = "0.74")
    private double confidence;

    @JsonProperty("relevance")
    @Schema(description = "Operational relevance score from 0.0 to 1.0.", example = "0.91")
    private double relevance;

    @JsonProperty("duplicate")
    @Schema(description = "Whether this article is likely a duplicate of already-known content.", example = "false")
    private boolean duplicate;

    @JsonProperty("propaganda")
    @Schema(description = "Whether the article shows propaganda indicators.", example = "false")
    private boolean propaganda;
}
