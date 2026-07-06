package it.osint.raven.services;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Reachability state for a configured external dependency.")
public enum ConnectionState {
    ONLINE("online"),
    OFFLINE("offline"),
    INVALID("invalid");

    private final String label;

    ConnectionState(String label) {
        this.label = label;
    }

    public String label() {
        return label;
    }
}
