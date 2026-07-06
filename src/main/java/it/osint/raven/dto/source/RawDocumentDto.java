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
import org.springframework.data.mongodb.core.mapping.Field;
import org.springframework.data.mongodb.core.mapping.FieldType;
import org.springframework.data.mongodb.core.mapping.MongoId;

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
@Document(collection = "raw_documents")
@Schema(description = "Raw acquired document before parser or intelligence enrichment.")
@CompoundIndexes({
        @CompoundIndex(
                name = "raw_documents_source_uri_unique",
                def = "{ 'source_id': 1, 'original_uri': 1 }",
                unique = true,
                sparse = true
        ),
        @CompoundIndex(
                name = "raw_documents_source_hash_unique",
                def = "{ 'source_id': 1, 'content_hash': 1 }",
                unique = true,
                sparse = true
        )
})
public class RawDocumentDto {

    @JsonProperty("id")
    @MongoId(FieldType.STRING)
    @Schema(description = "Raw document identifier.", example = "44f7a5ce-0d91-4f86-95f5-6427222b2964")
    private UUID id;

    @JsonProperty("source_id")
    @Field(targetType = FieldType.STRING)
    @Schema(description = "Source identifier that produced the raw document.", example = "12d6cbe1-e295-402e-83e4-66f15e4ce646")
    private UUID sourceId;

    @JsonProperty("original_uri")
    @Schema(description = "Original URI where the content was acquired.", example = "https://example.org/article")
    private URI originalUri;

    @JsonProperty("acquisition_time")
    @Indexed(name = "raw_documents_acquisition_time_idx", sparse = true)
    @Schema(description = "Time when Raven acquired the document.")
    private Instant acquisitionTime;

    @JsonProperty("content_timestamp")
    @Indexed(name = "raw_documents_content_timestamp_idx", sparse = true)
    @Schema(description = "Timestamp declared by the source content, when available.")
    private Instant contentTimestamp;

    @JsonProperty("mime_type")
    @Indexed(name = "raw_documents_mime_type_idx", sparse = true)
    @Schema(description = "MIME type of the raw content.", example = "text/html")
    private String mimeType;

    @JsonProperty("raw_content")
    @Schema(description = "Raw document bytes encoded as base64 in JSON payloads.", format = "byte")
    private byte[] rawContent;

    @JsonProperty("content_hash")
    @Schema(description = "Stable content hash used for deduplication.", example = "sha256:abc123")
    private String contentHash;

    @JsonProperty("metadata")
    @Schema(description = "Source-specific acquisition metadata.")
    @Builder.Default
    private Map<String, Object> metadata = new HashMap<>();
}
