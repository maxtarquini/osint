package it.osint.raven.dto.source;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

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
public class SourceDto {

    @JsonProperty("id")
    private UUID id;

    @JsonProperty("name")
    private String name;

    @JsonProperty("type")
    private SourceType type;

    @JsonProperty("endpoint")
    private URI endpoint;

    @JsonProperty("description")
    private String description;

    @JsonProperty("status")
    @Builder.Default
    private SourceStatus status = SourceStatus.ENABLED;

    @JsonProperty("priority")
    private int priority;

    @JsonProperty("polling_interval")
    private Duration pollingInterval;

    @JsonProperty("last_successful_run")
    private Instant lastSuccessfulRun;

    @JsonProperty("last_execution")
    private Instant lastExecution;

    @JsonProperty("last_content_timestamp")
    private Instant lastContentTimestamp;

    @JsonProperty("authentication")
    private AuthenticationDto authentication;

    @JsonProperty("configuration")
    @Builder.Default
    private Map<String, Object> configuration = new HashMap<>();

    @JsonProperty("tags")
    @Builder.Default
    private List<String> tags = new ArrayList<>();
}
