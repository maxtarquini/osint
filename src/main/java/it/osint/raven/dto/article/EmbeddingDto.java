package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.mongodb.core.mapping.Field;
import org.springframework.data.mongodb.core.mapping.FieldType;

import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Vector embedding associated with an article or extraction output.")
public class EmbeddingDto {

    @JsonProperty("embedding_id")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Embedding identifier.", example = "bc535758-90f1-4334-bb59-1805a5830f07")
    private UUID embeddingId;

    @JsonProperty("model")
    @Schema(description = "Embedding model name.", example = "text-embedding-3-large")
    private String model;

    @JsonProperty("dimensions")
    @Schema(description = "Number of vector dimensions.", example = "3072")
    private int dimensions;

    @JsonProperty("vector")
    @Schema(description = "Embedding vector values.")
    private float[] vector;
}
