package it.osint.raven;

import it.osint.raven.config.RavenConfiguration;
import it.osint.raven.config.RavenConfigurationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "raven.config.path=target/test-raven-context.yaml"
)
class RavenApplicationContextTest {

    @Autowired
    private RavenConfigurationService configurationService;

    @Test
    void startsSpringBootContextWithApplicationPropertiesDefaults() {
        RavenConfiguration configuration = configurationService.loadOrDefault();

        assertEquals("localhost", configuration.getNeo4j().getHost());
        assertEquals(7687, configuration.getNeo4j().getPort());
        assertEquals("localhost", configuration.getQdrant().getHost());
        assertEquals(6333, configuration.getQdrant().getHttpPort());
        assertEquals(6334, configuration.getQdrant().getGrpcPort());
        assertEquals("localhost", configuration.getMongodb().getHost());
        assertEquals(27017, configuration.getMongodb().getPort());
    }
}
