package it.osint.raven.controllers;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.ArraySchema;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import it.osint.raven.AppInfo;
import it.osint.raven.dto.system.ApiErrorResponse;
import it.osint.raven.dto.system.RavenConfigurationDto;
import it.osint.raven.services.ApplicationInfoService;
import it.osint.raven.services.ConnectionProbe;
import it.osint.raven.services.SystemConfigurationService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/system")
@Tag(name = "System", description = "System information, dependency checks and Raven configuration endpoints.")
@Slf4j
public class SystemController {

    private final ApplicationInfoService applicationInfoService;
    private final SystemConfigurationService systemConfigurationService;

    public SystemController(
            ApplicationInfoService applicationInfoService,
            SystemConfigurationService systemConfigurationService
    ) {
        this.applicationInfoService = applicationInfoService;
        this.systemConfigurationService = systemConfigurationService;
    }

    @GetMapping("/info")
    @Operation(summary = "Read application info", description = "Returns the Raven application name and version.")
    @ApiResponses({
            @ApiResponse(
                    responseCode = "200",
                    description = "Application info returned.",
                    content = @Content(schema = @Schema(implementation = AppInfo.class))
            )
    })
    public ResponseEntity<AppInfo> info() {
        return ResponseEntity.ok(applicationInfoService.info());
    }

    @GetMapping("/configuration")
    @Operation(
            summary = "Read Raven configuration",
            description = "Returns the effective Raven configuration after applying default values."
    )
    @ApiResponses({
            @ApiResponse(
                    responseCode = "200",
                    description = "Configuration returned.",
                    content = @Content(schema = @Schema(implementation = RavenConfigurationDto.class))
            )
    })
    public ResponseEntity<RavenConfigurationDto> configuration() {
        return ResponseEntity.ok(systemConfigurationService.currentConfiguration());
    }

    @PutMapping("/configuration")
    @Operation(
            summary = "Update Raven configuration",
            description = "Persists Raven external dependency configuration.",
            requestBody = @io.swagger.v3.oas.annotations.parameters.RequestBody(
                    description = "External dependency configuration to persist.",
                    required = true,
                    content = @Content(schema = @Schema(implementation = RavenConfigurationDto.class))
            )
    )
    @ApiResponses({
            @ApiResponse(
                    responseCode = "200",
                    description = "Configuration persisted and returned.",
                    content = @Content(schema = @Schema(implementation = RavenConfigurationDto.class))
            ),
            @ApiResponse(responseCode = "400", description = "Configuration request body is missing."),
            @ApiResponse(
                    responseCode = "500",
                    description = "Configuration could not be persisted.",
                    content = @Content(schema = @Schema(implementation = ApiErrorResponse.class))
            )
    })
    public ResponseEntity<RavenConfigurationDto> updateConfiguration(@RequestBody RavenConfigurationDto request) {
        if (request == null) {
            log.warn("Rejected empty configuration update request");
            return ResponseEntity.badRequest().build();
        }
        return ResponseEntity.ok(systemConfigurationService.updateConfiguration(request));
    }

    @GetMapping("/connections")
    @Operation(
            summary = "Check configured dependencies",
            description = "Runs TCP reachability probes for configured Neo4j, Qdrant and MongoDB endpoints."
    )
    @ApiResponses({
            @ApiResponse(
                    responseCode = "200",
                    description = "Connection probes returned.",
                    content = @Content(array = @ArraySchema(schema = @Schema(implementation = ConnectionProbe.class)))
            )
    })
    public ResponseEntity<List<ConnectionProbe>> connections() {
        return ResponseEntity.ok(systemConfigurationService.connectionStatus());
    }
}
