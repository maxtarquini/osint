package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Provenance metadata for parser or model extraction.")
public class ProvenanceDto {

    @JsonProperty("extraction_model")
    @Schema(description = "Model or extractor used for extraction.", example = "gpt-4.1")
    private String extractionModel;

    @JsonProperty("extraction_prompt")
    @Schema(description = "Prompt identifier or safe prompt reference. Raw prompts should not be exposed.", example = "article-extraction-v1")
    private String extractionPrompt;

    @JsonProperty("extraction_time")
    @Schema(description = "Time when extraction completed.")
    private Instant extractionTime;

    @JsonProperty("parser_version")
    @Schema(description = "Parser version used for structured extraction.", example = "1.0.0")
    private String parserVersion;
}
