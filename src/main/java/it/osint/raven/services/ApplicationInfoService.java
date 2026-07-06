package it.osint.raven.services;

import it.osint.raven.AppInfo;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class ApplicationInfoService {

    private final String name;
    private final String version;

    public ApplicationInfoService(
            @Value("${spring.application.name:raven}") String name,
            @Value("${raven.application.version:${project.version:0.1.0-SNAPSHOT}}") String version
    ) {
        this.name = name;
        this.version = version;
    }

    public AppInfo info() {
        return new AppInfo(name, version);
    }
}
