package it.osint.raven.repositories;

import it.osint.raven.dto.article.ArticleDto;
import it.osint.raven.dto.article.MetadataDto;
import it.osint.raven.dto.article.TaxonomyDto;
import it.osint.raven.dto.source.RawDocumentDto;
import it.osint.raven.dto.source.SourceDto;
import it.osint.raven.dto.source.SourceType;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.NONE,
        properties = {
                "raven.config.path=target/test-raven-mongo.yaml",
                "spring.data.mongodb.database=raven_test"
        }
)
class MongoRepositoryIntegrationTest {

    @Autowired
    private SourceRepository sourceRepository;

    @Autowired
    private RawDocumentRepository rawDocumentRepository;

    @Autowired
    private ArticleRepository articleRepository;

    @Test
    void persistsAndQueriesOsintDocumentsThroughSpringDataRepositories() {
        assumeTrue(mongoAvailable(), "MongoDB is not available on localhost:27017");

        SourceDto source = null;
        RawDocumentDto rawDocument = null;
        ArticleDto article = null;

        try {
            source = sourceRepository.save(SourceDto.builder()
                    .name("test-source-" + UUID.randomUUID())
                    .type(SourceType.RSS)
                    .endpoint(URI.create("https://example.org/feed.xml"))
                    .priority(3)
                    .pollingInterval(Duration.ofMinutes(15))
                    .tags(java.util.List.of("test"))
                    .build());

            rawDocument = rawDocumentRepository.save(RawDocumentDto.builder()
                    .sourceId(source.getId())
                    .originalUri(URI.create("https://example.org/article-" + UUID.randomUUID()))
                    .contentTimestamp(Instant.parse("2026-07-03T09:00:00Z"))
                    .mimeType("text/html")
                    .rawContent("<html></html>".getBytes(StandardCharsets.UTF_8))
                    .contentHash("sha256:" + UUID.randomUUID())
                    .build());

            article = articleRepository.save(ArticleDto.builder()
                    .rawDocumentId(rawDocument.getId())
                    .metadata(MetadataDto.builder()
                            .title("Repository smoke test")
                            .publicationDate(LocalDate.of(2026, 7, 3))
                            .build())
                    .taxonomy(TaxonomyDto.builder()
                            .domain("Security")
                            .eventType("incident")
                            .build())
                    .build());

            assertNotNull(source.getId());
            assertNotNull(rawDocument.getId());
            assertNotNull(rawDocument.getAcquisitionTime());
            assertNotNull(article.getId());

            assertEquals(source.getId(), sourceRepository.findByName(source.getName()).orElseThrow().getId());
            assertEquals(rawDocument.getId(), rawDocumentRepository
                    .findBySourceIdAndOriginalUri(source.getId(), rawDocument.getOriginalUri())
                    .orElseThrow()
                    .getId());
            assertEquals(article.getId(), articleRepository
                    .findByRawDocumentId(rawDocument.getId())
                    .orElseThrow()
                    .getId());
            assertFalse(articleRepository.findByTaxonomyDomain("Security", 10).isEmpty());
        } finally {
            if (article != null && article.getId() != null) {
                assertTrue(articleRepository.deleteExistingById(article.getId()));
            }
            if (rawDocument != null && rawDocument.getId() != null) {
                assertTrue(rawDocumentRepository.deleteExistingById(rawDocument.getId()));
            }
            if (source != null && source.getId() != null) {
                assertTrue(sourceRepository.deleteExistingById(source.getId()));
            }
        }
    }

    private static boolean mongoAvailable() {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress("localhost", 27017), 250);
            return true;
        } catch (Exception ex) {
            return false;
        }
    }
}
