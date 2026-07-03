package it.osint.raven;

import com.googlecode.lanterna.gui2.MultiWindowTextGUI;
import com.googlecode.lanterna.gui2.WindowBasedTextGUI;
import com.googlecode.lanterna.screen.Screen;
import com.googlecode.lanterna.terminal.DefaultTerminalFactory;
import com.googlecode.lanterna.terminal.MouseCaptureMode;

import it.osint.raven.config.RavenConfiguration;
import it.osint.raven.config.RavenConfigurationService;
import it.osint.raven.services.ConnectionStatusService;
import it.osint.raven.tui.RavenMainWindowFactory;

import java.io.IOException;

public class RavenApplication {

    private final RavenMainWindowFactory mainWindowFactory;
    private final RavenConfigurationService configurationService;

    public RavenApplication() {
        this(new RavenConfigurationService());
    }

    RavenApplication(RavenConfigurationService configurationService) {
        this(configurationService, new RavenMainWindowFactory(configurationService, new ConnectionStatusService()));
    }

    RavenApplication(RavenConfigurationService configurationService, RavenMainWindowFactory mainWindowFactory) {
        this.configurationService = configurationService;
        this.mainWindowFactory = mainWindowFactory;
    }

    public static void main(String[] args) throws IOException {
        RavenApplication application = new RavenApplication();
        application.run();
    }

    private void run() throws IOException {
        DefaultTerminalFactory terminalFactory = new DefaultTerminalFactory();
        RavenConfiguration configuration = configurationService.loadOrDefault();
        if (configuration.getUi().isMouseEnabled()) {
            terminalFactory.setMouseCaptureMode(MouseCaptureMode.CLICK_RELEASE_DRAG);
        }

        try (Screen screen = terminalFactory.createScreen()) {
            screen.startScreen();
            WindowBasedTextGUI gui = new MultiWindowTextGUI(screen);
            gui.addWindowAndWait(mainWindowFactory.createMainWindow());
        }
    }
}
        
