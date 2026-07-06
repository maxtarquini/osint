package it.osint.raven.services;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Reachability probe result for an external Raven dependency.")
public record ConnectionProbe(
        @Schema(description = "Dependency name.", example = "MongoDB")
        String name,
        @Schema(description = "Configured dependency host.", example = "localhost")
        String host,
        @Schema(description = "Configured dependency port.", example = "27017")
        int port,
        @Schema(description = "Probe state.")
        ConnectionState state
) {

    public String displayText() {
        return "%s: %s %s:%d".formatted(name, state.label(), host, port);
    }
}
