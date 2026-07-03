package it.osint.raven.dto.source;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.net.URI;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
public class RawDocumentDto {

    @JsonProperty("id")
    private UUID id;

    @JsonProperty("source_id")
    private UUID sourceId;

    @JsonProperty("original_uri")
    private URI originalUri;

    @JsonProperty("acquisition_time")
    private Instant acquisitionTime;

    @JsonProperty("content_timestamp")
    private Instant contentTimestamp;

    @JsonProperty("mime_type")
    private String mimeType;

    @JsonProperty("raw_content")
    private byte[] rawContent;

    @JsonProperty("content_hash")
    private String contentHash;

    @JsonProperty("metadata")
    @Builder.Default
    private Map<String, Object> metadata = new HashMap<>();
}
