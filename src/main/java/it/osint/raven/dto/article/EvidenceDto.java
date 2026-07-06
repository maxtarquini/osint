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

import java.net.URI;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Evidence item supporting an extracted claim or assessment.")
public class EvidenceDto {

    @JsonProperty("id")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Evidence identifier.", example = "9c85bf36-7ad8-4494-ad5d-ef01fd9b75cb")
    private UUID id;

    @JsonProperty("type")
    @Schema(description = "Evidence type.", example = "ARTICLE_TEXT")
    private EvidenceType type;

    @JsonProperty("source")
    @Schema(description = "Evidence source label.", example = "Article paragraph 4")
    private String source;

    @JsonProperty("url")
    @Schema(description = "External evidence URL, when available.", example = "https://example.org/source")
    private URI url;

    @JsonProperty("excerpt")
    @Schema(description = "Short excerpt supporting the claim.")
    private String excerpt;

    @JsonProperty("locator")
    @Schema(description = "Locator within the source document.", example = "paragraph:4")
    private String locator;

    @JsonProperty("confidence")
    @Schema(description = "Evidence confidence score from 0.0 to 1.0.", example = "0.74")
    private double confidence;
}
