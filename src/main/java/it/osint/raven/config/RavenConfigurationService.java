package it.osint.raven.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class RavenConfigurationService {

    public static final Path DEFAULT_CONFIG_PATH = Path.of("config", "raven.yaml");

    private final ObjectMapper objectMapper;
    private final Path configPath;
    private final RavenConfiguration defaults;

    public RavenConfigurationService() {
        this(DEFAULT_CONFIG_PATH);
    }

    @Autowired
    public RavenConfigurationService(RavenProperties properties) {
        this(Path.of(properties.getConfigPath()), properties.toConfiguration());
    }

    public RavenConfigurationService(Path configPath) {
        this(configPath, RavenConfiguration.defaults());
    }

    RavenConfigurationService(Path configPath, RavenConfiguration defaults) {
        this(new ObjectMapper(new YAMLFactory()).findAndRegisterModules(), configPath, defaults);
    }

    RavenConfigurationService(ObjectMapper objectMapper, Path configPath, RavenConfiguration defaults) {
        this.objectMapper = objectMapper;
        this.configPath = configPath;
        this.defaults = mergeWithHardcodedDefaults(defaults);
    }

    public RavenConfiguration loadOrDefault() {
        if (!Files.exists(configPath)) {
            return defaults;
        }
        try {
            RavenConfiguration configuration = objectMapper.readValue(configPath.toFile(), RavenConfiguration.class);
            return mergeWithDefaults(configuration);
        } catch (IOException ex) {
            return defaults;
        }
    }

    public void save(RavenConfiguration configuration) throws IOException {
        if (configPath.getParent() != null) {
            Files.createDirectories(configPath.getParent());
        }
        objectMapper.writerWithDefaultPrettyPrinter().writeValue(configPath.toFile(), mergeWithDefaults(configuration));
    }

    public Path configPath() {
        return configPath;
    }

    private RavenConfiguration mergeWithDefaults(RavenConfiguration configuration) {
        if (configuration == null) {
            return defaults;
        }

        EndpointConfiguration neo4j = normalizeEndpoint(configuration.getNeo4j(), defaults.getNeo4j());
        QdrantConfiguration qdrant = normalizeQdrant(configuration.getQdrant(), defaults.getQdrant());
        EndpointConfiguration mongodb = normalizeEndpoint(configuration.getMongodb(), defaults.getMongodb());
        return new RavenConfiguration(neo4j, qdrant, mongodb);
    }

    private static RavenConfiguration mergeWithHardcodedDefaults(RavenConfiguration configuration) {
        RavenConfiguration fallback = RavenConfiguration.defaults();
        if (configuration == null) {
            return fallback;
        }
        EndpointConfiguration neo4j = normalizeEndpoint(configuration.getNeo4j(), fallback.getNeo4j());
        QdrantConfiguration qdrant = normalizeQdrant(configuration.getQdrant(), fallback.getQdrant());
        EndpointConfiguration mongodb = normalizeEndpoint(configuration.getMongodb(), fallback.getMongodb());
        return new RavenConfiguration(neo4j, qdrant, mongodb);
    }

    private static EndpointConfiguration normalizeEndpoint(EndpointConfiguration value, EndpointConfiguration defaults) {
        if (value == null) {
            return defaults;
        }
        String host = hasText(value.getHost()) ? value.getHost().trim() : defaults.getHost();
        int port = validPort(value.getPort()) ? value.getPort() : defaults.getPort();
        return new EndpointConfiguration(host, port);
    }

    private static QdrantConfiguration normalizeQdrant(QdrantConfiguration value, QdrantConfiguration defaults) {
        if (value == null) {
            return defaults;
        }
        String host = hasText(value.getHost()) ? value.getHost().trim() : defaults.getHost();
        int httpPort = validPort(value.getHttpPort()) ? value.getHttpPort() : defaults.getHttpPort();
        int grpcPort = validPort(value.getGrpcPort()) ? value.getGrpcPort() : defaults.getGrpcPort();
        return new QdrantConfiguration(host, httpPort, grpcPort);
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private static boolean validPort(int port) {
        return port > 0 && port <= 65535;
    }
}
