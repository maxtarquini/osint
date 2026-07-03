package it.osint.raven.tui;

import com.googlecode.lanterna.TextColor;
import com.googlecode.lanterna.gui2.Button;
import com.googlecode.lanterna.gui2.Component;
import com.googlecode.lanterna.gui2.Container;
import com.googlecode.lanterna.gui2.Label;
import com.googlecode.lanterna.gui2.Window;
import it.osint.raven.config.RavenConfigurationService;
import it.osint.raven.config.ThemeConfiguration;
import it.osint.raven.services.ConnectionProbe;
import it.osint.raven.services.ConnectionState;
import it.osint.raven.services.ConnectionStatusService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RavenMainWindowFactoryTest {

    @TempDir
    Path tempDir;

    @Test
    void createsFullScreenRavenWindow() {
        RavenMainWindowFactory factory = factory();
        Window window = factory.createMainWindow();

        assertEquals("Raven", window.getTitle());
        assertTrue(window.getHints().contains(Window.Hint.FULL_SCREEN));
        assertTrue(window.getHints().contains(Window.Hint.NO_DECORATIONS));
        assertInstanceOf(Container.class, window.getComponent());
    }

    @Test
    void rendersExpectedStartupContent() {
        RavenMainWindowFactory factory = factory();
        Window window = factory.createMainWindow();

        List<String> labels = flattenComponents(window.getComponent()).stream()
                .filter(Label.class::isInstance)
                .map(Label.class::cast)
                .map(Label::getText)
                .toList();

        assertTrue(labels.contains("raven 0.1.0-SNAPSHOT"));
        assertTrue(labels.contains("- Lanterna TUI"));
        assertTrue(labels.contains("- Neo4j Java Driver"));
        assertTrue(labels.contains("- Qdrant Java Client"));
        assertTrue(labels.contains("- MongoDB Java Driver"));
        assertTrue(labels.contains("- LangChain4j"));
        assertTrue(labels.contains("- LangGraph4j"));
        assertTrue(labels.contains("Navigation"));
        assertTrue(labels.contains("F1 Help  F2 Config  F5 Refresh  q Exit"));
        assertTrue(labels.contains("Mouse enabled"));
        assertTrue(labels.contains("Density: COMFORTABLE"));
    }

    @Test
    void exposesTopBarActions() {
        RavenMainWindowFactory factory = factory();
        Window window = factory.createMainWindow();

        List<String> buttonLabels = flattenComponents(window.getComponent()).stream()
                .filter(Button.class::isInstance)
                .map(Button.class::cast)
                .map(Button::getLabel)
                .toList();

        assertEquals(List.of("Refresh", "Config", "Exit", "Dashboard", "Graph", "Agents", "Config", "Logs"), buttonLabels);
    }

    @Test
    void rendersConnectionStatusLabels() {
        RavenMainWindowFactory factory = factory();
        Window window = factory.createMainWindow();

        List<String> labels = flattenComponents(window.getComponent()).stream()
                .filter(Label.class::isInstance)
                .map(Label.class::cast)
                .map(Label::getText)
                .toList();

        assertTrue(labels.stream().anyMatch(text -> text.startsWith("Neo4j:")));
        assertTrue(labels.stream().anyMatch(text -> text.startsWith("Qdrant HTTP:")));
        assertTrue(labels.stream().anyMatch(text -> text.startsWith("Qdrant gRPC:")));
        assertTrue(labels.stream().anyMatch(text -> text.startsWith("MongoDB:")));
    }

    @Test
    void rendersOnlineStatusWithNeonGreen() {
        Label label = RavenMainWindowFactory.createStatusLabel(
                new ConnectionProbe("Qdrant HTTP", "localhost", 6333, ConnectionState.ONLINE)
        );

        assertEquals("Qdrant HTTP: online localhost:6333  ", label.getText());
        assertEquals(TextColor.ANSI.GREEN_BRIGHT, label.getForegroundColor());
        assertEquals(TextColor.ANSI.BLACK, label.getBackgroundColor());
    }

    @Test
    void rendersOfflineStatusWithNeonRed() {
        Label label = RavenMainWindowFactory.createStatusLabel(
                new ConnectionProbe("Neo4j", "localhost", 7687, ConnectionState.OFFLINE)
        );

        assertEquals("Neo4j: offline localhost:7687  ", label.getText());
        assertEquals(TextColor.ANSI.RED_BRIGHT, label.getForegroundColor());
        assertEquals(TextColor.ANSI.BLACK, label.getBackgroundColor());
    }

    @Test
    void rendersInvalidStatusWithNeonYellow() {
        Label label = RavenMainWindowFactory.createStatusLabel(
                new ConnectionProbe("MongoDB", " ", 0, ConnectionState.INVALID)
        );

        assertEquals(TextColor.ANSI.YELLOW_BRIGHT, label.getForegroundColor());
        assertEquals(TextColor.ANSI.BLACK, label.getBackgroundColor());
    }

    @Test
    void rendersStatusWithConfiguredThemeColors() {
        ThemeConfiguration theme = new ThemeConfiguration("CYAN_BRIGHT", "MAGENTA_BRIGHT", "WHITE_BRIGHT");

        Label online = RavenMainWindowFactory.createStatusLabel(
                new ConnectionProbe("Qdrant HTTP", "localhost", 6333, ConnectionState.ONLINE),
                theme
        );
        Label offline = RavenMainWindowFactory.createStatusLabel(
                new ConnectionProbe("Neo4j", "localhost", 7687, ConnectionState.OFFLINE),
                theme
        );
        Label invalid = RavenMainWindowFactory.createStatusLabel(
                new ConnectionProbe("MongoDB", "localhost", 0, ConnectionState.INVALID),
                theme
        );

        assertEquals(TextColor.ANSI.CYAN_BRIGHT, online.getForegroundColor());
        assertEquals(TextColor.ANSI.MAGENTA_BRIGHT, offline.getForegroundColor());
        assertEquals(TextColor.ANSI.WHITE_BRIGHT, invalid.getForegroundColor());
    }

    @Test
    void configWindowContainsExternalDependencyFields() {
        RavenMainWindowFactory factory = factory();
        Window configWindow = factory.createConfigWindow(
                new AtomicReference<>(RavenConfigurationService.DEFAULT_CONFIG_PATH.isAbsolute()
                        ? new RavenConfigurationService().loadOrDefault()
                        : new RavenConfigurationService(tempDir.resolve("raven.yaml")).loadOrDefault()),
                List.of(new Label("Neo4j"), new Label("Qdrant HTTP"), new Label("Qdrant gRPC"), new Label("MongoDB"))
        );

        List<String> labels = flattenComponents(configWindow.getComponent()).stream()
                .filter(Label.class::isInstance)
                .map(Label.class::cast)
                .map(Label::getText)
                .toList();

        assertTrue(labels.contains("External dependencies"));
        assertTrue(labels.contains("Neo4j host: "));
        assertTrue(labels.contains("Neo4j port: "));
        assertTrue(labels.contains("Qdrant host: "));
        assertTrue(labels.contains("Qdrant HTTP: "));
        assertTrue(labels.contains("Qdrant gRPC: "));
        assertTrue(labels.contains("MongoDB host: "));
        assertTrue(labels.contains("MongoDB port: "));
        assertTrue(labels.contains("Status colors"));
        assertTrue(labels.contains("Online color: "));
        assertTrue(labels.contains("Offline color: "));
        assertTrue(labels.contains("Invalid color: "));
        assertTrue(labels.contains("Interface"));
        assertTrue(labels.contains("UI density: "));
    }

    private static List<Component> flattenComponents(Component component) {
        List<Component> components = new ArrayList<>();
        components.add(component);
        if (component instanceof Container container) {
            container.getChildrenList().forEach(child -> components.addAll(flattenComponents(child)));
        }
        return components;
    }

    private RavenMainWindowFactory factory() {
        return new RavenMainWindowFactory(
                new RavenConfigurationService(tempDir.resolve("raven.yaml")),
                new ConnectionStatusService()
        );
    }
}
