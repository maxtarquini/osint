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

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Schema(description = "Event extracted from an article.")
public class EventDto {

    @JsonProperty("id")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Event identifier.", example = "f35ce6f8-7784-4f99-9f7c-d0a179a618d0")
    private UUID id;

    @JsonProperty("type")
    @Schema(description = "Event type label.", example = "diplomatic_meeting")
    private String type;

    @JsonProperty("date")
    @Schema(description = "Event date when available.", example = "2026-07-03")
    private LocalDate date;

    @JsonProperty("description")
    @Schema(description = "Short event description.", example = "Delegations resumed negotiations in Tripoli.")
    private String description;

    @JsonProperty("participants")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Entity identifiers participating in the event.")
    @Builder.Default
    private List<UUID> participants = new ArrayList<>();

    @JsonProperty("locations")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Entity identifiers representing event locations.")
    @Builder.Default
    private List<UUID> locations = new ArrayList<>();
}
