package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class EmbeddingDto {

    @JsonProperty("embedding_id")
    private UUID embeddingId;

    @JsonProperty("model")
    private String model;

    @JsonProperty("dimensions")
    private int dimensions;

    @JsonProperty("vector")
    private float[] vector;
}
