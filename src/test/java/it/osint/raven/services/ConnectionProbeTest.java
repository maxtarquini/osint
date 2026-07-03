package it.osint.raven.services;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class ConnectionProbeTest {

    @Test
    void formatsDisplayTextForTopBar() {
        ConnectionProbe probe = new ConnectionProbe("Qdrant HTTP", "localhost", 6333, ConnectionState.ONLINE);

        assertEquals("Qdrant HTTP: online localhost:6333", probe.displayText());
    }
}
