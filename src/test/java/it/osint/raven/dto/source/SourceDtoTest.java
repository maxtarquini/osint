package it.osint.raven.dto.source;

import com.fasterxml.jackson.databind.ObjectMapper;
import it.osint.raven.utils.OsintObjectMapper;
import org.junit.jupiter.api.Test;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SourceDtoTest {

    private final ObjectMapper objectMapper = OsintObjectMapper.create();

    @Test
    void serializesSourceUsingSnakeCaseOperationalFields() throws Exception {
        SourceDto source = SourceDto.builder()
                .id(UUID.fromString("12d6cbe1-e295-402e-83e4-66f15e4ce646"))
                .name("Libya Observer RSS")
                .type(SourceType.RSS)
                .endpoint(URI.create("https://example.org/feed.xml"))
                .priority(10)
                .pollingInterval(Duration.ofMinutes(30))
                .lastSuccessfulRun(Instant.parse("2026-07-03T08:00:00Z"))
                .configuration(Map.of("maxItems", 100))
                .tags(java.util.List.of("Libia", "Politica"))
                .build();

        String json = objectMapper.writeValueAsString(source);

        assertTrue(json.contains("\"polling_interval\":\"PT30M\""));
        assertTrue(json.contains("\"last_successful_run\":\"2026-07-03T08:00:00Z\""));
        assertTrue(json.contains("\"configuration\":{\"maxItems\":100}"));
        assertTrue(json.contains("\"tags\":[\"Libia\",\"Politica\"]"));
        assertTrue(json.contains("\"status\":\"ENABLED\""));
    }

    @Test
    void deserializesRawDocumentAsGenericAcquisitionUnit() throws Exception {
        String json = """
                {
                  "id": "44f7a5ce-0d91-4f86-95f5-6427222b2964",
                  "source_id": "12d6cbe1-e295-402e-83e4-66f15e4ce646",
                  "original_uri": "https://example.org/article",
                  "acquisition_time": "2026-07-03T09:30:00Z",
                  "content_timestamp": "2026-07-03T09:00:00Z",
                  "mime_type": "text/html",
                  "raw_content": "PGh0bWw+PC9odG1sPg==",
                  "content_hash": "sha256:test",
                  "metadata": {
                    "http_status": 200
                  }
                }
                """;

        RawDocumentDto rawDocument = objectMapper.readValue(json, RawDocumentDto.class);

        assertEquals(UUID.fromString("44f7a5ce-0d91-4f86-95f5-6427222b2964"), rawDocument.getId());
        assertEquals(UUID.fromString("12d6cbe1-e295-402e-83e4-66f15e4ce646"), rawDocument.getSourceId());
        assertEquals("text/html", rawDocument.getMimeType());
        assertArrayEquals("<html></html>".getBytes(StandardCharsets.UTF_8), rawDocument.getRawContent());
        assertEquals(200, rawDocument.getMetadata().get("http_status"));
    }
}
