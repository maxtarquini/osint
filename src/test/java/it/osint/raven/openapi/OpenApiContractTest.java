package it.osint.raven.openapi;

import com.fasterxml.jackson.databind.JsonNode;
import it.osint.raven.AppInfo;
import it.osint.raven.dto.article.ArticleDto;
import it.osint.raven.dto.article.AssessmentDto;
import it.osint.raven.dto.article.ClaimDto;
import it.osint.raven.dto.article.ClaimType;
import it.osint.raven.dto.article.Confidence;
import it.osint.raven.dto.article.EmbeddingDto;
import it.osint.raven.dto.article.EntityDto;
import it.osint.raven.dto.article.EntityType;
import it.osint.raven.dto.article.EventDto;
import it.osint.raven.dto.article.EvidenceDto;
import it.osint.raven.dto.article.EvidenceType;
import it.osint.raven.dto.article.IntelligenceAssessmentDto;
import it.osint.raven.dto.article.LinksDto;
import it.osint.raven.dto.article.MetadataDto;
import it.osint.raven.dto.article.ProvenanceDto;
import it.osint.raven.dto.article.RelationshipDto;
import it.osint.raven.dto.article.TaxonomyDto;
import it.osint.raven.dto.source.AuthenticationDto;
import it.osint.raven.dto.source.AuthenticationType;
import it.osint.raven.dto.source.RawDocumentDto;
import it.osint.raven.dto.source.SourceDto;
import it.osint.raven.dto.source.SourceStatus;
import it.osint.raven.dto.source.SourceType;
import it.osint.raven.dto.system.ApiErrorResponse;
import it.osint.raven.dto.system.EndpointConfigurationDto;
import it.osint.raven.dto.system.QdrantConfigurationDto;
import it.osint.raven.dto.system.RavenConfigurationDto;
import it.osint.raven.services.ConnectionProbe;
import it.osint.raven.services.ConnectionState;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpStatus;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "raven.config.path=target/test-raven-openapi.yaml"
)
class OpenApiContractTest {

    private static final List<String> EXPECTED_PATHS = List.of(
            "/api/system/info",
            "/api/system/configuration",
            "/api/system/connections"
    );

    private static final List<Class<?>> EXPECTED_SCHEMAS = List.of(
            AppInfo.class,
            ConnectionProbe.class,
            ConnectionState.class,
            ApiErrorResponse.class,
            EndpointConfigurationDto.class,
            QdrantConfigurationDto.class,
            RavenConfigurationDto.class,
            AuthenticationDto.class,
            AuthenticationType.class,
            SourceDto.class,
            SourceStatus.class,
            SourceType.class,
            RawDocumentDto.class,
            ArticleDto.class,
            AssessmentDto.class,
            ClaimDto.class,
            ClaimType.class,
            Confidence.class,
            EmbeddingDto.class,
            EntityDto.class,
            EntityType.class,
            EventDto.class,
            EvidenceDto.class,
            EvidenceType.class,
            IntelligenceAssessmentDto.class,
            LinksDto.class,
            MetadataDto.class,
            ProvenanceDto.class,
            RelationshipDto.class,
            TaxonomyDto.class
    );

    @LocalServerPort
    private int port;

    private final HttpClient httpClient = HttpClient.newBuilder()
            .followRedirects(HttpClient.Redirect.NORMAL)
            .build();

    @Test
    void exposesStableOpenApiDocument() throws Exception {
        HttpResponse<String> response = get("/v3/api-docs");

        assertEquals(HttpStatus.OK.value(), response.statusCode());
        JsonNode document = new com.fasterxml.jackson.databind.ObjectMapper().readTree(response.body());
        assertTrue(document.path("openapi").asText().startsWith("3."), "OpenAPI 3 document is required");
        assertEquals("Raven OSINT API", document.path("info").path("title").asText());

        JsonNode paths = document.path("paths");
        for (String expectedPath : EXPECTED_PATHS) {
            assertTrue(paths.has(expectedPath), () -> "Missing OpenAPI path " + expectedPath);
        }

        JsonNode schemas = document.path("components").path("schemas");
        for (Class<?> expectedSchema : EXPECTED_SCHEMAS) {
            assertTrue(schemas.has(expectedSchema.getSimpleName()), () -> "Missing schema " + expectedSchema.getSimpleName());
        }
    }

    @Test
    void documentsSwaggerUiEndpoint() throws Exception {
        HttpResponse<String> response = get("/swagger-ui.html");

        assertEquals(HttpStatus.OK.value(), response.statusCode());
        assertFalse(response.body().isBlank());
    }

    private HttpResponse<String> get(String path) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://localhost:" + port + path))
                .GET()
                .build();
        return httpClient.send(request, HttpResponse.BodyHandlers.ofString());
    }
}
