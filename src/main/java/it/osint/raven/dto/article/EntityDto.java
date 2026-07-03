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
public class EntityDto {

    @JsonProperty("id")
    private UUID id;

    @JsonProperty("type")
    private EntityType type;

    @JsonProperty("name")
    private String name;

    @JsonProperty("normalized_name")
    private String normalizedName;

    @JsonProperty("wikidata_id")
    private String wikidataId;

    @JsonProperty("confidence")
    private double confidence;
}
