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
@Schema(description = "Named entity extracted from an article.")
public class EntityDto {

    @JsonProperty("id")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Entity identifier.", example = "d5ea33fb-55c1-435b-a72d-0649675f7db5")
    private UUID id;

    @JsonProperty("type")
    @Schema(description = "Entity type.", example = "ORGANIZATION")
    private EntityType type;

    @JsonProperty("name")
    @Schema(description = "Entity display name as found or normalized from text.", example = "United Nations")
    private String name;

    @JsonProperty("normalized_name")
    @Schema(description = "Normalized entity name for matching and lookup.", example = "united nations")
    private String normalizedName;

    @JsonProperty("wikidata_id")
    @Schema(description = "Optional Wikidata identifier.", example = "Q1065")
    private String wikidataId;

    @JsonProperty("confidence")
    @Schema(description = "Entity extraction confidence score from 0.0 to 1.0.", example = "0.88")
    private double confidence;
}
