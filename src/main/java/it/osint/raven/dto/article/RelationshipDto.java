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
@Schema(description = "Relationship between two extracted entities.")
public class RelationshipDto {

    @JsonProperty("source")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Source entity identifier.")
    private UUID source;

    @JsonProperty("target")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Target entity identifier.")
    private UUID target;

    @JsonProperty("predicate")
    @Schema(description = "Relationship predicate.", example = "supports")
    private String predicate;

    @JsonProperty("confidence")
    @Schema(description = "Relationship confidence score from 0.0 to 1.0.", example = "0.67")
    private double confidence;
}
