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
public class RelationshipDto {

    @JsonProperty("source")
    private UUID source;

    @JsonProperty("target")
    private UUID target;

    @JsonProperty("predicate")
    private String predicate;

    @JsonProperty("confidence")
    private double confidence;
}
