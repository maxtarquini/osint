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
@Schema(description = "Claim or assertion extracted from a structured article.")
public class ClaimDto {

    @JsonProperty("id")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Claim identifier.", example = "a22f07c8-8c8b-4da4-a234-9bdc037c12e2")
    private UUID id;

    @JsonProperty("source_entity_id")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Entity identifier for the claimant or source entity.")
    private UUID sourceEntityId;

    @JsonProperty("statement")
    @Schema(description = "Normalized claim statement.", example = "Actor A supports Actor B")
    private String statement;

    @JsonProperty("target_entity_ids")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Entity identifiers referenced as claim targets.")
    @Builder.Default
    private List<UUID> targetEntityIds = new ArrayList<>();

    @JsonProperty("date")
    @Schema(description = "Claim date when explicitly present in the article.", example = "2026-07-03")
    private LocalDate date;

    @JsonProperty("type")
    @Schema(description = "Claim semantic type.", example = "FACTUAL_ASSERTION")
    private ClaimType type;

    @JsonProperty("confidence")
    @Schema(description = "Qualitative confidence level for the claim.", example = "MEDIUM")
    private Confidence confidence;

    @JsonProperty("evidence")
    @Schema(description = "Evidence items supporting the claim.")
    @Builder.Default
    private List<EvidenceDto> evidence = new ArrayList<>();
}
