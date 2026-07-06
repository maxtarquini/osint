package it.osint.raven.config;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class RavenConfiguration {
    private EndpointConfiguration neo4j;
    private QdrantConfiguration qdrant;
    private EndpointConfiguration mongodb;

    public static RavenConfiguration defaults() {
        return new RavenConfiguration(
                new EndpointConfiguration("localhost", 7687),
                new QdrantConfiguration("localhost", 6333, 6334),
                new EndpointConfiguration("localhost", 27017)
        );
    }
}
