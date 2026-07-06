package it.osint.raven.services;

import it.osint.raven.config.RavenConfiguration;
import it.osint.raven.config.RavenConfigurationService;
import it.osint.raven.dto.system.RavenConfigurationDto;
import it.osint.raven.exceptions.ConfigurationUpdateException;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.util.List;
import java.util.Objects;

@Service
public class SystemConfigurationService {

    private final RavenConfigurationService configurationService;
    private final ConnectionStatusService connectionStatusService;

    public SystemConfigurationService(
            RavenConfigurationService configurationService,
            ConnectionStatusService connectionStatusService
    ) {
        this.configurationService = configurationService;
        this.connectionStatusService = connectionStatusService;
    }

    public RavenConfigurationDto currentConfiguration() {
        return RavenConfigurationDto.fromDomain(configurationService.loadOrDefault());
    }

    public RavenConfigurationDto updateConfiguration(RavenConfigurationDto request) {
        Objects.requireNonNull(request, "request must not be null");
        RavenConfiguration configuration = request.toDomain();
        try {
            configurationService.save(configuration);
            return RavenConfigurationDto.fromDomain(configurationService.loadOrDefault());
        } catch (IOException ex) {
            throw new ConfigurationUpdateException("Unable to save Raven configuration.", ex);
        }
    }

    public List<ConnectionProbe> connectionStatus() {
        return connectionStatusService.check(configurationService.loadOrDefault());
    }
}
