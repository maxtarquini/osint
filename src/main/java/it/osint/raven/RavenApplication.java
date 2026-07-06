package it.osint.raven;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class RavenApplication {

    public static void main(String[] args) {
        SpringApplication.run(RavenApplication.class, args);
    }
}
        
