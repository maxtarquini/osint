package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
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
public class ProvenanceDto {

    @JsonProperty("extraction_model")
    private String extractionModel;

    @JsonProperty("extraction_prompt")
    private String extractionPrompt;

    @JsonProperty("extraction_time")
    private Instant extractionTime;

    @JsonProperty("parser_version")
    private String parserVersion;
}
