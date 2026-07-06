package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Publication metadata for a structured article.")
public class MetadataDto {

    @JsonProperty("title")
    @Schema(description = "Article title.", example = "Tripoli security update")
    private String title;

    @JsonProperty("subtitle")
    @Schema(description = "Article subtitle, when available.")
    private String subtitle;

    @JsonProperty("author")
    @Schema(description = "Article author or source byline.", example = "Editorial desk")
    private String author;

    @JsonProperty("publication_date")
    @Schema(description = "Publication date.", example = "2026-07-03")
    private LocalDate publicationDate;

    @JsonProperty("category")
    @Schema(description = "Source-provided article category.", example = "Security")
    private String category;

    @JsonProperty("tags")
    @Schema(description = "Source-provided or inferred article tags.")
    @Builder.Default
    private List<String> tags = new ArrayList<>();

    @JsonProperty("images")
    @Schema(description = "Image URLs or identifiers associated with the article.")
    @Builder.Default
    private List<String> images = new ArrayList<>();

    @JsonProperty("attachments")
    @Schema(description = "Attachment URLs or identifiers associated with the article.")
    @Builder.Default
    private List<String> attachments = new ArrayList<>();
}
