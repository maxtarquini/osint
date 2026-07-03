package it.osint.raven.services;

public record ConnectionProbe(String name, String host, int port, ConnectionState state) {

    public String displayText() {
        return "%s: %s %s:%d".formatted(name, state.label(), host, port);
    }
}
