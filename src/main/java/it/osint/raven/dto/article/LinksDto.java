package it.osint.raven.dto.article;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class LinksDto {

    @JsonProperty("related_articles")
    @Builder.Default
    private List<UUID> relatedArticles = new ArrayList<>();

    @JsonProperty("previous_events")
    @Builder.Default
    private List<UUID> previousEvents = new ArrayList<>();

    @JsonProperty("follow_up_events")
    @Builder.Default
    private List<UUID> followUpEvents = new ArrayList<>();
}
