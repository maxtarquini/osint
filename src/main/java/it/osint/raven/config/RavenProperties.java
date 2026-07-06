package it.osint.raven.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "raven")
public class RavenProperties {

    private String configPath = RavenConfigurationService.DEFAULT_CONFIG_PATH.toString();
    private EndpointConfiguration neo4j = RavenConfiguration.defaults().getNeo4j();
    private QdrantConfiguration qdrant = RavenConfiguration.defaults().getQdrant();
    private EndpointConfiguration mongodb = RavenConfiguration.defaults().getMongodb();

    public String getConfigPath() {
        return configPath;
    }

    public void setConfigPath(String configPath) {
        this.configPath = configPath;
    }

    public EndpointConfiguration getNeo4j() {
        return neo4j;
    }

    public void setNeo4j(EndpointConfiguration neo4j) {
        this.neo4j = neo4j;
    }

    public QdrantConfiguration getQdrant() {
        return qdrant;
    }

    public void setQdrant(QdrantConfiguration qdrant) {
        this.qdrant = qdrant;
    }

    public EndpointConfiguration getMongodb() {
        return mongodb;
    }

    public void setMongodb(EndpointConfiguration mongodb) {
        this.mongodb = mongodb;
    }

    public RavenConfiguration toConfiguration() {
        RavenConfiguration fallback = RavenConfiguration.defaults();
        return new RavenConfiguration(
                neo4j == null ? fallback.getNeo4j() : neo4j,
                qdrant == null ? fallback.getQdrant() : qdrant,
                mongodb == null ? fallback.getMongodb() : mongodb
        );
    }
}
