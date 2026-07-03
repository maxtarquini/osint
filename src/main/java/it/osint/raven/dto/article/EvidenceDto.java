package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.net.URI;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class EvidenceDto {

    @JsonProperty("id")
    private UUID id;

    @JsonProperty("type")
    private EvidenceType type;

    @JsonProperty("source")
    private String source;

    @JsonProperty("url")
    private URI url;

    @JsonProperty("excerpt")
    private String excerpt;

    @JsonProperty("locator")
    private String locator;

    @JsonProperty("confidence")
    private double confidence;
}
