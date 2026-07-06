package it.osint.raven.dto.system;

import io.swagger.v3.oas.annotations.media.Schema;
import it.osint.raven.config.EndpointConfiguration;

@Schema(description = "Host and port configuration for a TCP dependency.")
public record EndpointConfigurationDto(
        @Schema(description = "Dependency host.", example = "localhost")
        String host,
        @Schema(description = "Dependency port.", example = "27017")
        int port
) {

    public static EndpointConfigurationDto fromDomain(EndpointConfiguration configuration) {
        return new EndpointConfigurationDto(configuration.getHost(), configuration.getPort());
    }

    public EndpointConfiguration toDomain() {
        return new EndpointConfiguration(host, port);
    }
}
