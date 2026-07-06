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

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "References between articles and extracted events.")
public class LinksDto {

    @JsonProperty("related_articles")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Identifiers of related articles.")
    @Builder.Default
    private List<UUID> relatedArticles = new ArrayList<>();

    @JsonProperty("previous_events")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Identifiers of previous related events.")
    @Builder.Default
    private List<UUID> previousEvents = new ArrayList<>();

    @JsonProperty("follow_up_events")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Identifiers of follow-up related events.")
    @Builder.Default
    private List<UUID> followUpEvents = new ArrayList<>();
}
