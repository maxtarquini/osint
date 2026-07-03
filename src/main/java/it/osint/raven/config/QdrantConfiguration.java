package it.osint.raven.config;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class QdrantConfiguration {
    private String host;
    private int httpPort;
    private int grpcPort;
}
