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
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class EventDto {

    @JsonProperty("id")
    private UUID id;

    @JsonProperty("type")
    private String type;

    @JsonProperty("date")
    private LocalDate date;

    @JsonProperty("description")
    private String description;

    @JsonProperty("participants")
    @Builder.Default
    private List<UUID> participants = new ArrayList<>();

    @JsonProperty("locations")
    @Builder.Default
    private List<UUID> locations = new ArrayList<>();
}
