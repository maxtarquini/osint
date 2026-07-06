package it.osint.raven.dto.system;

import io.swagger.v3.oas.annotations.media.Schema;
import it.osint.raven.config.QdrantConfiguration;

@Schema(description = "Qdrant HTTP and gRPC endpoint configuration.")
public record QdrantConfigurationDto(
        @Schema(description = "Qdrant host.", example = "localhost")
        String host,
        @Schema(description = "Qdrant HTTP port.", example = "6333")
        int httpPort,
        @Schema(description = "Qdrant gRPC port.", example = "6334")
        int grpcPort
) {

    public static QdrantConfigurationDto fromDomain(QdrantConfiguration configuration) {
        return new QdrantConfigurationDto(
                configuration.getHost(),
                configuration.getHttpPort(),
                configuration.getGrpcPort()
        );
    }

    public QdrantConfiguration toDomain() {
        return new QdrantConfiguration(host, httpPort, grpcPort);
    }
}
