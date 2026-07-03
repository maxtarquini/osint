package it.osint.raven.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

public class RavenConfigurationService {

    public static final Path DEFAULT_CONFIG_PATH = Path.of("config", "raven.yaml");

    private final ObjectMapper objectMapper;
    private final Path configPath;

    public RavenConfigurationService() {
        this(DEFAULT_CONFIG_PATH);
    }

    public RavenConfigurationService(Path configPath) {
        this(new ObjectMapper(new YAMLFactory()).findAndRegisterModules(), configPath);
    }

    RavenConfigurationService(ObjectMapper objectMapper, Path configPath) {
        this.objectMapper = objectMapper;
        this.configPath = configPath;
    }

    public RavenConfiguration loadOrDefault() {
        if (!Files.exists(configPath)) {
            return RavenConfiguration.defaults();
        }
        try {
            RavenConfiguration configuration = objectMapper.readValue(configPath.toFile(), RavenConfiguration.class);
            return mergeWithDefaults(configuration);
        } catch (IOException ex) {
            return RavenConfiguration.defaults();
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

    private static RavenConfiguration mergeWithDefaults(RavenConfiguration configuration) {
        RavenConfiguration defaults = RavenConfiguration.defaults();
        if (configuration == null) {
            return defaults;
        }

        EndpointConfiguration neo4j = normalizeEndpoint(configuration.getNeo4j(), defaults.getNeo4j());
        QdrantConfiguration qdrant = normalizeQdrant(configuration.getQdrant(), defaults.getQdrant());
        EndpointConfiguration mongodb = normalizeEndpoint(configuration.getMongodb(), defaults.getMongodb());
        ThemeConfiguration theme = normalizeTheme(configuration.getTheme(), defaults.getTheme());
        UiConfiguration ui = normalizeUi(configuration.getUi(), defaults.getUi());
        return new RavenConfiguration(neo4j, qdrant, mongodb, theme, ui);
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

    private static ThemeConfiguration normalizeTheme(ThemeConfiguration value, ThemeConfiguration defaults) {
        if (value == null) {
            return defaults;
        }
        return new ThemeConfiguration(
                normalizeColor(value.getOnlineColor(), defaults.getOnlineColor()),
                normalizeColor(value.getOfflineColor(), defaults.getOfflineColor()),
                normalizeColor(value.getInvalidColor(), defaults.getInvalidColor())
        );
    }

    private static String normalizeColor(String value, String defaultValue) {
        if (!hasText(value)) {
            return defaultValue;
        }
        String normalized = value.trim().toUpperCase();
        return switch (normalized) {
            case "GREEN_BRIGHT", "RED_BRIGHT", "YELLOW_BRIGHT", "CYAN_BRIGHT", "MAGENTA_BRIGHT", "BLUE_BRIGHT", "WHITE_BRIGHT" -> normalized;
            default -> defaultValue;
        };
    }

    private static UiConfiguration normalizeUi(UiConfiguration value, UiConfiguration defaults) {
        if (value == null) {
            return defaults;
        }
        return new UiConfiguration(value.isMouseEnabled(), normalizeDensity(value.getDensity(), defaults.getDensity()));
    }

    private static String normalizeDensity(String value, String defaultValue) {
        if (!hasText(value)) {
            return defaultValue;
        }
        String normalized = value.trim().toUpperCase();
        return switch (normalized) {
            case "COMPACT", "COMFORTABLE", "LARGE" -> normalized;
            default -> defaultValue;
        };
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private static boolean validPort(int port) {
        return port > 0 && port <= 65535;
    }
}
