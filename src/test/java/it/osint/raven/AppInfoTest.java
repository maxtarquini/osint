package it.osint.raven;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class AppInfoTest {

    @Test
    void exposesApplicationNameAndVersion() {
        AppInfo appInfo = new AppInfo("raven", "0.1.0-SNAPSHOT");

        assertEquals("raven", appInfo.getName());
        assertEquals("0.1.0-SNAPSHOT", appInfo.getVersion());
    }
}
