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
public class ClaimDto {

    @JsonProperty("id")
    private UUID id;

    @JsonProperty("source_entity_id")
    private UUID sourceEntityId;

    @JsonProperty("statement")
    private String statement;

    @JsonProperty("target_entity_ids")
    @Builder.Default
    private List<UUID> targetEntityIds = new ArrayList<>();

    @JsonProperty("date")
    private LocalDate date;

    @JsonProperty("type")
    private ClaimType type;

    @JsonProperty("confidence")
    private Confidence confidence;

    @JsonProperty("evidence")
    @Builder.Default
    private List<EvidenceDto> evidence = new ArrayList<>();
}
