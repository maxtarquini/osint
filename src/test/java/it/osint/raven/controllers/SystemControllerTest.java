package it.osint.raven.controllers;

import it.osint.raven.AppInfo;
import it.osint.raven.dto.system.EndpointConfigurationDto;
import it.osint.raven.dto.system.QdrantConfigurationDto;
import it.osint.raven.dto.system.RavenConfigurationDto;
import it.osint.raven.services.ApplicationInfoService;
import it.osint.raven.services.ConnectionProbe;
import it.osint.raven.services.ConnectionState;
import it.osint.raven.services.SystemConfigurationService;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class SystemControllerTest {

    @Test
    void returnsApplicationInfo() {
        SystemController controller = new SystemController(
                new ApplicationInfoService("raven", "0.1.0-SNAPSHOT"),
                new StubSystemConfigurationService(configuration(), List.of())
        );

        ResponseEntity<AppInfo> response = controller.info();

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("raven", response.getBody().getName());
        assertEquals("0.1.0-SNAPSHOT", response.getBody().getVersion());
    }

    @Test
    void returnsEffectiveConfiguration() {
        RavenConfigurationDto configuration = configuration();
        SystemController controller = new SystemController(
                new ApplicationInfoService("raven", "0.1.0-SNAPSHOT"),
                new StubSystemConfigurationService(configuration, List.of())
        );

        ResponseEntity<RavenConfigurationDto> response = controller.configuration();

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(configuration, response.getBody());
    }

    @Test
    void rejectsEmptyConfigurationUpdate() {
        SystemController controller = new SystemController(
                new ApplicationInfoService("raven", "0.1.0-SNAPSHOT"),
                new StubSystemConfigurationService(configuration(), List.of())
        );

        ResponseEntity<RavenConfigurationDto> response = controller.updateConfiguration(null);

        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
        assertNull(response.getBody());
    }

    @Test
    void returnsConnectionStatus() {
        List<ConnectionProbe> probes = List.of(
                new ConnectionProbe("MongoDB", "localhost", 27017, ConnectionState.OFFLINE)
        );
        SystemController controller = new SystemController(
                new ApplicationInfoService("raven", "0.1.0-SNAPSHOT"),
                new StubSystemConfigurationService(configuration(), probes)
        );

        ResponseEntity<List<ConnectionProbe>> response = controller.connections();

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(probes, response.getBody());
    }

    private static RavenConfigurationDto configuration() {
        return new RavenConfigurationDto(
                new EndpointConfigurationDto("localhost", 7687),
                new QdrantConfigurationDto("localhost", 6333, 6334),
                new EndpointConfigurationDto("localhost", 27017)
        );
    }

    private static final class StubSystemConfigurationService extends SystemConfigurationService {

        private final RavenConfigurationDto configuration;
        private final List<ConnectionProbe> probes;

        private StubSystemConfigurationService(RavenConfigurationDto configuration, List<ConnectionProbe> probes) {
            super(null, null);
            this.configuration = configuration;
            this.probes = probes;
        }

        @Override
        public RavenConfigurationDto currentConfiguration() {
            return configuration;
        }

        @Override
        public RavenConfigurationDto updateConfiguration(RavenConfigurationDto request) {
            return request;
        }

        @Override
        public List<ConnectionProbe> connectionStatus() {
            return probes;
        }
    }
}
