package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
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
public class MetadataDto {

    @JsonProperty("title")
    private String title;

    @JsonProperty("subtitle")
    private String subtitle;

    @JsonProperty("author")
    private String author;

    @JsonProperty("publication_date")
    private LocalDate publicationDate;

    @JsonProperty("category")
    private String category;

    @JsonProperty("tags")
    @Builder.Default
    private List<String> tags = new ArrayList<>();

    @JsonProperty("images")
    @Builder.Default
    private List<String> images = new ArrayList<>();

    @JsonProperty("attachments")
    @Builder.Default
    private List<String> attachments = new ArrayList<>();
}
