package it.osint.raven.tui;

import com.googlecode.lanterna.SGR;
import com.googlecode.lanterna.TerminalSize;
import com.googlecode.lanterna.TextColor;
import com.googlecode.lanterna.gui2.BasicWindow;
import com.googlecode.lanterna.gui2.Borders;
import com.googlecode.lanterna.gui2.Button;
import com.googlecode.lanterna.gui2.CheckBox;
import com.googlecode.lanterna.gui2.ComboBox;
import com.googlecode.lanterna.gui2.Component;
import com.googlecode.lanterna.gui2.Direction;
import com.googlecode.lanterna.gui2.EmptySpace;
import com.googlecode.lanterna.gui2.Label;
import com.googlecode.lanterna.gui2.LinearLayout;
import com.googlecode.lanterna.gui2.Panel;
import com.googlecode.lanterna.gui2.Separator;
import com.googlecode.lanterna.gui2.TextBox;
import com.googlecode.lanterna.gui2.Window;
import it.osint.raven.config.EndpointConfiguration;
import it.osint.raven.config.QdrantConfiguration;
import it.osint.raven.config.RavenConfiguration;
import it.osint.raven.config.RavenConfigurationService;
import it.osint.raven.config.ThemeConfiguration;
import it.osint.raven.config.UiConfiguration;
import it.osint.raven.services.ConnectionProbe;
import it.osint.raven.services.ConnectionState;
import it.osint.raven.services.ConnectionStatusService;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Pattern;

public class RavenMainWindowFactory {

    private static final Pattern PORT_PATTERN = Pattern.compile("\\d{0,5}");
    private static final List<String> THEME_COLORS = List.of(
            "GREEN_BRIGHT",
            "RED_BRIGHT",
            "YELLOW_BRIGHT",
            "CYAN_BRIGHT",
            "MAGENTA_BRIGHT",
            "BLUE_BRIGHT",
            "WHITE_BRIGHT"
    );
    private static final List<String> UI_DENSITIES = List.of("COMPACT", "COMFORTABLE", "LARGE");

    private final RavenConfigurationService configurationService;
    private final ConnectionStatusService connectionStatusService;

    public RavenMainWindowFactory() {
        this(new RavenConfigurationService(), new ConnectionStatusService());
    }

    public RavenMainWindowFactory(
            RavenConfigurationService configurationService,
            ConnectionStatusService connectionStatusService
    ) {
        this.configurationService = configurationService;
        this.connectionStatusService = connectionStatusService;
    }

    public Window createMainWindow() {
        BasicWindow window = new BasicWindow("Raven");
        AtomicReference<RavenConfiguration> configuration = new AtomicReference<>(configurationService.loadOrDefault());
        Density density = Density.from(configuration.get().getUi().getDensity());

        Panel root = new Panel(new LinearLayout(Direction.VERTICAL));
        List<Label> statusLabels = createStatusLabels(configuration.get());
        root.addComponent(createTopBar(window, configuration, statusLabels, density));
        root.addComponent(createBody(window, configuration, statusLabels),
                LinearLayout.createLayoutData(LinearLayout.Alignment.Fill, LinearLayout.GrowPolicy.CanGrow));
        root.addComponent(createFooter(configuration.get(), configurationService.configPath().toString()));

        window.setComponent(root);
        window.setHints(List.of(Window.Hint.FULL_SCREEN, Window.Hint.NO_DECORATIONS));
        return window;
    }

    private Component createTopBar(
            BasicWindow mainWindow,
            AtomicReference<RavenConfiguration> configuration,
            List<Label> statusLabels,
            Density density
    ) {
        Panel topBar = new Panel(new LinearLayout(Direction.HORIZONTAL).setSpacing(density.spacing()));
        topBar.addComponent(new Button("Refresh", () -> updateStatusLabels(statusLabels, configuration.get())));
        topBar.addComponent(new Button("Config", () -> openConfigWindow(mainWindow, configuration, statusLabels)));
        topBar.addComponent(new Button("Exit", mainWindow::close));
        topBar.addComponent(new EmptySpace(new TerminalSize(density.gap(), 0)));
        statusLabels.forEach(topBar::addComponent);
        return topBar.withBorder(Borders.singleLine("Raven"));
    }

    private Panel createBody(
            BasicWindow mainWindow,
            AtomicReference<RavenConfiguration> configuration,
            List<Label> statusLabels
    ) {
        Density density = Density.from(configuration.get().getUi().getDensity());
        Panel body = new Panel(new LinearLayout(Direction.HORIZONTAL).setSpacing(density.spacing()));
        body.addComponent(createSidebar(mainWindow, configuration, statusLabels));
        body.addComponent(createDashboard(density),
                LinearLayout.createLayoutData(LinearLayout.Alignment.Fill, LinearLayout.GrowPolicy.CanGrow));
        return body;
    }

    private Component createSidebar(
            BasicWindow mainWindow,
            AtomicReference<RavenConfiguration> configuration,
            List<Label> statusLabels
    ) {
        Density density = Density.from(configuration.get().getUi().getDensity());
        Panel sidebar = new Panel(new LinearLayout(Direction.VERTICAL).setSpacing(density.spacing()));
        sidebar.addComponent(new Label("Navigation"));
        sidebar.addComponent(new Separator(Direction.HORIZONTAL));
        sidebar.addComponent(new Button("Dashboard", () -> {
        }));
        sidebar.addComponent(new Button("Graph", () -> {
        }));
        sidebar.addComponent(new Button("Agents", () -> {
        }));
        sidebar.addComponent(new Button("Config", () -> openConfigWindow(mainWindow, configuration, statusLabels)));
        sidebar.addComponent(new Button("Logs", () -> {
        }));
        sidebar.addComponent(new EmptySpace(new TerminalSize(0, density.gap())));
        sidebar.addComponent(new Label("F5 Refresh"));
        sidebar.addComponent(new Label("F2 Config"));
        sidebar.addComponent(new Label("q Exit"));
        sidebar.addComponent(new Label(configuration.get().getUi().isMouseEnabled() ? "Mouse enabled" : "Mouse disabled"));
        return sidebar.withBorder(Borders.singleLine("Menu"));
    }

    private Component createDashboard(Density density) {
        Panel dashboard = new Panel(new LinearLayout(Direction.VERTICAL).setSpacing(density.spacing()));
        dashboard.addComponent(new Label("raven 0.1.0-SNAPSHOT"));
        dashboard.addComponent(new Label("Terminal workspace for OSINT graph and agent workflows."));
        if (density == Density.LARGE) {
            dashboard.addComponent(new Label("Large density is active. Increase the terminal font with your terminal shortcuts for true font scaling."));
        }
        dashboard.addComponent(new Separator(Direction.HORIZONTAL));

        Panel modules = new Panel(new LinearLayout(Direction.VERTICAL).setSpacing(density.spacing()));
        modules.addComponent(new Label("- Lanterna TUI"));
        modules.addComponent(new Label("- Neo4j Java Driver"));
        modules.addComponent(new Label("- Qdrant Java Client"));
        modules.addComponent(new Label("- MongoDB Java Driver"));
        modules.addComponent(new Label("- LangChain4j"));
        modules.addComponent(new Label("- LangGraph4j"));
        dashboard.addComponent(modules.withBorder(Borders.singleLine("Ready Modules")));

        Panel nextActions = new Panel(new LinearLayout(Direction.VERTICAL).setSpacing(density.spacing()));
        nextActions.addComponent(new Label("- Refresh connection probes from the top bar."));
        nextActions.addComponent(new Label("- Open Config to edit external dependency endpoints."));
        nextActions.addComponent(new Label("- Use the sidebar as Raven grows into graph and agent workflows."));
        dashboard.addComponent(nextActions.withBorder(Borders.singleLine("Dashboard")));
        return dashboard.withBorder(Borders.singleLine("Workspace"));
    }

    private Component createFooter(RavenConfiguration configuration, String configPath) {
        Density density = Density.from(configuration.getUi().getDensity());
        Panel footer = new Panel(new LinearLayout(Direction.HORIZONTAL).setSpacing(density.spacing()));
        footer.addComponent(new Label("F1 Help  F2 Config  F5 Refresh  q Exit"));
        footer.addComponent(new EmptySpace(new TerminalSize(density.gap(), 0)));
        footer.addComponent(new Label(configuration.getUi().isMouseEnabled() ? "Mouse enabled" : "Mouse disabled"));
        footer.addComponent(new EmptySpace(new TerminalSize(density.gap(), 0)));
        footer.addComponent(new Label("Density: " + density.name()));
        footer.addComponent(new EmptySpace(new TerminalSize(density.gap(), 0)));
        footer.addComponent(new Label("Config: " + configPath));
        return footer.withBorder(Borders.singleLine("Status"));
    }

    private List<Label> createStatusLabels(RavenConfiguration configuration) {
        return connectionStatusService.check(configuration).stream()
                .map(probe -> createStatusLabel(probe, configuration.getTheme()))
                .toList();
    }

    private void updateStatusLabels(List<Label> statusLabels, RavenConfiguration configuration) {
        List<ConnectionProbe> probes = connectionStatusService.check(configuration);
        for (int index = 0; index < statusLabels.size() && index < probes.size(); index++) {
            applyStatusStyle(statusLabels.get(index), probes.get(index), configuration.getTheme());
        }
    }

    static Label createStatusLabel(ConnectionProbe probe) {
        return createStatusLabel(probe, ThemeConfiguration.defaults());
    }

    static Label createStatusLabel(ConnectionProbe probe, ThemeConfiguration theme) {
        Label label = new Label("");
        applyStatusStyle(label, probe, theme);
        return label;
    }

    private static void applyStatusStyle(Label label, ConnectionProbe probe, ThemeConfiguration theme) {
        label.setText(probe.displayText() + "  ");
        label.setBackgroundColor(TextColor.ANSI.BLACK);
        label.addStyle(SGR.BOLD);
        label.setForegroundColor(statusColor(probe.state(), theme));
    }

    private static TextColor statusColor(ConnectionState state, ThemeConfiguration theme) {
        return switch (state) {
            case ONLINE -> ansiColor(theme.getOnlineColor(), TextColor.ANSI.GREEN_BRIGHT);
            case OFFLINE -> ansiColor(theme.getOfflineColor(), TextColor.ANSI.RED_BRIGHT);
            case INVALID -> ansiColor(theme.getInvalidColor(), TextColor.ANSI.YELLOW_BRIGHT);
        };
    }

    private static TextColor ansiColor(String colorName, TextColor fallback) {
        if (colorName == null || colorName.isBlank()) {
            return fallback;
        }
        try {
            return TextColor.ANSI.valueOf(colorName.trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            return fallback;
        }
    }

    private void openConfigWindow(
            BasicWindow mainWindow,
            AtomicReference<RavenConfiguration> currentConfiguration,
            List<Label> statusLabels
    ) {
        Window configWindow = createConfigWindow(currentConfiguration, statusLabels);
        mainWindow.getTextGUI().addWindowAndWait(configWindow);
    }

    Window createConfigWindow(
            AtomicReference<RavenConfiguration> currentConfiguration,
            List<Label> statusLabels
    ) {
        RavenConfiguration configuration = currentConfiguration.get();
        BasicWindow window = new BasicWindow("Config");
        Panel root = new Panel(new LinearLayout(Direction.VERTICAL));
        root.addComponent(new Label("External dependencies"));

        TextBox neo4jHost = textBox(configuration.getNeo4j().getHost());
        TextBox neo4jPort = portBox(configuration.getNeo4j().getPort());
        TextBox qdrantHost = textBox(configuration.getQdrant().getHost());
        TextBox qdrantHttpPort = portBox(configuration.getQdrant().getHttpPort());
        TextBox qdrantGrpcPort = portBox(configuration.getQdrant().getGrpcPort());
        TextBox mongodbHost = textBox(configuration.getMongodb().getHost());
        TextBox mongodbPort = portBox(configuration.getMongodb().getPort());
        ComboBox<String> onlineColor = colorBox(configuration.getTheme().getOnlineColor());
        ComboBox<String> offlineColor = colorBox(configuration.getTheme().getOfflineColor());
        ComboBox<String> invalidColor = colorBox(configuration.getTheme().getInvalidColor());
        CheckBox mouseEnabled = new CheckBox("Enable mouse input").setChecked(configuration.getUi().isMouseEnabled());
        ComboBox<String> density = densityBox(configuration.getUi().getDensity());
        Label feedback = new Label("Config file: " + configurationService.configPath());

        root.addComponent(row("Neo4j host", neo4jHost));
        root.addComponent(row("Neo4j port", neo4jPort));
        root.addComponent(row("Qdrant host", qdrantHost));
        root.addComponent(row("Qdrant HTTP", qdrantHttpPort));
        root.addComponent(row("Qdrant gRPC", qdrantGrpcPort));
        root.addComponent(row("MongoDB host", mongodbHost));
        root.addComponent(row("MongoDB port", mongodbPort));
        root.addComponent(new Separator(Direction.HORIZONTAL));
        root.addComponent(new Label("Status colors"));
        root.addComponent(row("Online color", onlineColor));
        root.addComponent(row("Offline color", offlineColor));
        root.addComponent(row("Invalid color", invalidColor));
        root.addComponent(new Separator(Direction.HORIZONTAL));
        root.addComponent(new Label("Interface"));
        root.addComponent(mouseEnabled);
        root.addComponent(row("UI density", density));
        root.addComponent(new Separator(Direction.HORIZONTAL));
        root.addComponent(feedback);

        Panel actions = new Panel(new LinearLayout(Direction.HORIZONTAL));
        actions.addComponent(new Button("Save", () -> {
            try {
                RavenConfiguration updated = new RavenConfiguration(
                        new EndpointConfiguration(neo4jHost.getText(), parsePort(neo4jPort.getText())),
                        new QdrantConfiguration(
                                qdrantHost.getText(),
                                parsePort(qdrantHttpPort.getText()),
                                parsePort(qdrantGrpcPort.getText())
                        ),
                        new EndpointConfiguration(mongodbHost.getText(), parsePort(mongodbPort.getText())),
                        new ThemeConfiguration(
                                onlineColor.getSelectedItem(),
                                offlineColor.getSelectedItem(),
                                invalidColor.getSelectedItem()
                        ),
                        new UiConfiguration(
                                mouseEnabled.isChecked(),
                                density.getSelectedItem()
                        )
                );
                configurationService.save(updated);
                RavenConfiguration normalized = configurationService.loadOrDefault();
                currentConfiguration.set(normalized);
                updateStatusLabels(statusLabels, normalized);
                window.close();
            } catch (IOException | IllegalArgumentException ex) {
                feedback.setText("Save failed: " + safeMessage(ex));
            }
        }));
        actions.addComponent(new Button("Cancel", window::close));
        root.addComponent(actions);

        window.setComponent(root.withBorder(Borders.singleLine("Dependency Config")));
        window.setHints(List.of(Window.Hint.CENTERED));
        return window;
    }

    private static Panel row(String label, TextBox textBox) {
        Panel row = new Panel(new LinearLayout(Direction.HORIZONTAL));
        row.addComponent(new Label(label + ": "));
        row.addComponent(textBox);
        return row;
    }

    private static Panel row(String label, ComboBox<String> comboBox) {
        Panel row = new Panel(new LinearLayout(Direction.HORIZONTAL));
        row.addComponent(new Label(label + ": "));
        row.addComponent(comboBox);
        return row;
    }

    private static TextBox textBox(String value) {
        return new TextBox(new TerminalSize(28, 1), value == null ? "" : value);
    }

    private static TextBox portBox(int port) {
        return new TextBox(new TerminalSize(8, 1), String.valueOf(port))
                .setValidationPattern(PORT_PATTERN);
    }

    private static ComboBox<String> colorBox(String selectedColor) {
        ComboBox<String> comboBox = new ComboBox<>(THEME_COLORS);
        comboBox.setReadOnly(true);
        comboBox.setSelectedItem(THEME_COLORS.contains(selectedColor) ? selectedColor : "WHITE_BRIGHT");
        return comboBox;
    }

    private static ComboBox<String> densityBox(String selectedDensity) {
        ComboBox<String> comboBox = new ComboBox<>(UI_DENSITIES);
        comboBox.setReadOnly(true);
        comboBox.setSelectedItem(UI_DENSITIES.contains(selectedDensity) ? selectedDensity : "COMFORTABLE");
        return comboBox;
    }

    private static int parsePort(String value) {
        try {
            int port = Integer.parseInt(value);
            if (port <= 0 || port > 65535) {
                throw new IllegalArgumentException("port must be between 1 and 65535");
            }
            return port;
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("port must be numeric", ex);
        }
    }

    private static String safeMessage(Exception ex) {
        return ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage();
    }

    private enum Density {
        COMPACT(0, 1),
        COMFORTABLE(1, 2),
        LARGE(2, 4);

        private final int spacing;
        private final int gap;

        Density(int spacing, int gap) {
            this.spacing = spacing;
            this.gap = gap;
        }

        static Density from(String value) {
            if (value == null || value.isBlank()) {
                return COMFORTABLE;
            }
            try {
                return Density.valueOf(value.trim().toUpperCase());
            } catch (IllegalArgumentException ex) {
                return COMFORTABLE;
            }
        }

        int spacing() {
            return spacing;
        }

        int gap() {
            return gap;
        }
    }
}
