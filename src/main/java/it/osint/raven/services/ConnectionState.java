package it.osint.raven.services;

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
