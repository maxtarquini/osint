package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class TaxonomyDto {

    @JsonProperty("domain")
    private String domain;

    @JsonProperty("sub_domain")
    private String subDomain;

    @JsonProperty("event_type")
    private String eventType;

    @JsonProperty("sector")
    private String sector;

    @JsonProperty("impact_level")
    private String impactLevel;

    @JsonProperty("topics")
    @Builder.Default
    private List<String> topics = new ArrayList<>();

    @JsonProperty("keywords")
    @Builder.Default
    private List<String> keywords = new ArrayList<>();
}
