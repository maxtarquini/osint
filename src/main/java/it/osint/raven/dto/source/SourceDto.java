package it.osint.raven.dto.source;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.mongodb.core.index.CompoundIndex;
import org.springframework.data.mongodb.core.index.CompoundIndexes;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;
import org.springframework.data.mongodb.core.mapping.FieldType;
import org.springframework.data.mongodb.core.mapping.MongoId;

import java.net.URI;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@Document(collection = "sources")
@Schema(description = "Operational OSINT source configuration.")
@CompoundIndexes({
        @CompoundIndex(name = "sources_type_endpoint_idx", def = "{ 'type': 1, 'endpoint': 1 }", sparse = true),
        @CompoundIndex(name = "sources_status_priority_idx", def = "{ 'status': 1, 'priority': 1 }", sparse = true)
})
public class SourceDto {

    @JsonProperty("id")
    @MongoId(FieldType.STRING)
    @Schema(description = "Source identifier.", example = "12d6cbe1-e295-402e-83e4-66f15e4ce646")
    private UUID id;

    @JsonProperty("name")
    @Indexed(name = "sources_name_unique", unique = true, sparse = true)
    @Schema(description = "Human-readable unique source name.", example = "Libya Observer RSS")
    private String name;

    @JsonProperty("type")
    @Schema(description = "Source acquisition type.", example = "RSS")
    private SourceType type;

    @JsonProperty("endpoint")
    @Schema(description = "Source endpoint URI.", example = "https://example.org/feed.xml")
    private URI endpoint;

    @JsonProperty("description")
    @Schema(description = "Operational description of the source.", example = "RSS feed monitored for North Africa political reporting.")
    private String description;

    @JsonProperty("status")
    @Schema(description = "Whether the source is enabled for acquisition.", example = "ENABLED")
    @Builder.Default
    private SourceStatus status = SourceStatus.ENABLED;

    @JsonProperty("priority")
    @Schema(description = "Lower values are processed first.", example = "10")
    private int priority;

    @JsonProperty("polling_interval")
    @Schema(description = "Polling interval expressed as an ISO-8601 duration.", example = "PT30M")
    private Duration pollingInterval;

    @JsonProperty("last_successful_run")
    @Schema(description = "Last successful acquisition time.")
    private Instant lastSuccessfulRun;

    @JsonProperty("last_execution")
    @Schema(description = "Last attempted acquisition time.")
    private Instant lastExecution;

    @JsonProperty("last_content_timestamp")
    @Schema(description = "Most recent content timestamp observed from this source.")
    private Instant lastContentTimestamp;

    @JsonProperty("authentication")
    @Schema(description = "Authentication configuration used by the source.")
    private AuthenticationDto authentication;

    @JsonProperty("configuration")
    @Schema(description = "Source-specific non-secret connector configuration.")
    @Builder.Default
    private Map<String, Object> configuration = new HashMap<>();

    @JsonProperty("tags")
    @Indexed(name = "sources_tags_idx", sparse = true)
    @Schema(description = "Operational tags used to organize sources.", example = "[\"Libia\",\"Politica\"]")
    @Builder.Default
    private List<String> tags = new ArrayList<>();
}
