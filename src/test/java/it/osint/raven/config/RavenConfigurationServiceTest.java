package it.osint.raven.config;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RavenConfigurationServiceTest {

    @TempDir
    Path tempDir;

    @Test
    void returnsDefaultsWhenYamlDoesNotExist() {
        RavenConfigurationService service = new RavenConfigurationService(tempDir.resolve("raven.yaml"));

        RavenConfiguration configuration = service.loadOrDefault();

        assertEquals("localhost", configuration.getNeo4j().getHost());
        assertEquals(7687, configuration.getNeo4j().getPort());
        assertEquals("localhost", configuration.getQdrant().getHost());
        assertEquals(6333, configuration.getQdrant().getHttpPort());
        assertEquals(6334, configuration.getQdrant().getGrpcPort());
        assertEquals("localhost", configuration.getMongodb().getHost());
        assertEquals(27017, configuration.getMongodb().getPort());
    }

    @Test
    void savesAndLoadsYamlConfiguration() throws IOException {
        Path configPath = tempDir.resolve("config").resolve("raven.yaml");
        RavenConfigurationService service = new RavenConfigurationService(configPath);
        RavenConfiguration configuration = new RavenConfiguration(
                new EndpointConfiguration("neo4j.local", 17687),
                new QdrantConfiguration("qdrant.local", 16333, 16334),
                new EndpointConfiguration("mongo.local", 37017)
        );

        service.save(configuration);
        RavenConfiguration loaded = service.loadOrDefault();

        assertTrue(Files.exists(configPath));
        assertEquals("neo4j.local", loaded.getNeo4j().getHost());
        assertEquals(17687, loaded.getNeo4j().getPort());
        assertEquals("qdrant.local", loaded.getQdrant().getHost());
        assertEquals(16333, loaded.getQdrant().getHttpPort());
        assertEquals(16334, loaded.getQdrant().getGrpcPort());
        assertEquals("mongo.local", loaded.getMongodb().getHost());
        assertEquals(37017, loaded.getMongodb().getPort());
    }

    @Test
    void invalidOrBlankValuesFallBackToDefaults() throws IOException {
        Path configPath = tempDir.resolve("raven.yaml");
        Files.writeString(configPath, """
                neo4j:
                  host: " "
                  port: 999999
                qdrant:
                  host: qdrant.local
                  httpPort: -1
                  grpcPort: 6335
                mongodb:
                  host: mongo.local
                  port: 0
                """);
        RavenConfigurationService service = new RavenConfigurationService(configPath);

        RavenConfiguration loaded = service.loadOrDefault();

        assertEquals("localhost", loaded.getNeo4j().getHost());
        assertEquals(7687, loaded.getNeo4j().getPort());
        assertEquals("qdrant.local", loaded.getQdrant().getHost());
        assertEquals(6333, loaded.getQdrant().getHttpPort());
        assertEquals(6335, loaded.getQdrant().getGrpcPort());
        assertEquals("mongo.local", loaded.getMongodb().getHost());
        assertEquals(27017, loaded.getMongodb().getPort());
    }
}
