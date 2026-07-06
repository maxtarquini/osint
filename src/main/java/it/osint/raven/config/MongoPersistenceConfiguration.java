package it.osint.raven.config;

import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import it.osint.raven.dto.article.ArticleDto;
import it.osint.raven.dto.source.RawDocumentDto;
import it.osint.raven.dto.source.SourceDto;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.mongodb.MongoDatabaseFactory;
import org.springframework.data.mongodb.core.SimpleMongoClientDatabaseFactory;
import org.springframework.data.mongodb.core.mapping.event.BeforeConvertCallback;

import java.time.Instant;
import java.util.UUID;

@Configuration
public class MongoPersistenceConfiguration {

    public static final String DEFAULT_RAVEN_DATABASE_NAME = "raven";

    @Bean
    MongoClient ravenMongoClient(RavenConfigurationService configurationService) {
        EndpointConfiguration mongodb = configurationService.loadOrDefault().getMongodb();
        return MongoClients.create("mongodb://%s:%d".formatted(mongodb.getHost(), mongodb.getPort()));
    }

    @Bean
    MongoDatabaseFactory mongoDatabaseFactory(
            MongoClient ravenMongoClient,
            @Value("${spring.data.mongodb.database:raven}") String databaseName
    ) {
        return new SimpleMongoClientDatabaseFactory(ravenMongoClient, databaseName);
    }

    @Bean
    BeforeConvertCallback<SourceDto> sourceDefaultsCallback() {
        return (source, collection) -> {
            if (source.getId() == null) {
                source.setId(UUID.randomUUID());
            }
            return source;
        };
    }

    @Bean
    BeforeConvertCallback<RawDocumentDto> rawDocumentDefaultsCallback() {
        return (rawDocument, collection) -> {
            if (rawDocument.getId() == null) {
                rawDocument.setId(UUID.randomUUID());
            }
            if (rawDocument.getAcquisitionTime() == null) {
                rawDocument.setAcquisitionTime(Instant.now());
            }
            return rawDocument;
        };
    }

    @Bean
    BeforeConvertCallback<ArticleDto> articleDefaultsCallback() {
        return (article, collection) -> {
            if (article.getId() == null) {
                article.setId(UUID.randomUUID());
            }
            return article;
        };
    }
}
