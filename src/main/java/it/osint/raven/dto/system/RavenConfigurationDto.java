package it.osint.raven.dto.system;

import io.swagger.v3.oas.annotations.media.Schema;
import it.osint.raven.config.RavenConfiguration;

@Schema(description = "Raven external dependency and compatibility configuration.")
public record RavenConfigurationDto(
        @Schema(description = "Neo4j endpoint configuration.")
        EndpointConfigurationDto neo4j,
        @Schema(description = "Qdrant endpoint configuration.")
        QdrantConfigurationDto qdrant,
        @Schema(description = "MongoDB endpoint configuration.")
        EndpointConfigurationDto mongodb
) {

    public static RavenConfigurationDto fromDomain(RavenConfiguration configuration) {
        return new RavenConfigurationDto(
                EndpointConfigurationDto.fromDomain(configuration.getNeo4j()),
                QdrantConfigurationDto.fromDomain(configuration.getQdrant()),
                EndpointConfigurationDto.fromDomain(configuration.getMongodb())
        );
    }

    public RavenConfiguration toDomain() {
        RavenConfiguration defaults = RavenConfiguration.defaults();
        return new RavenConfiguration(
                neo4j == null ? defaults.getNeo4j() : neo4j.toDomain(),
                qdrant == null ? defaults.getQdrant() : qdrant.toDomain(),
                mongodb == null ? defaults.getMongodb() : mongodb.toDomain()
        );
    }
}
