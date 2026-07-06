package it.osint.raven;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Value;

@Schema(description = "Application identity exposed by the REST API.")
@Value
public class AppInfo {
    @Schema(description = "Application name.", example = "raven")
    String name;

    @Schema(description = "Application version.", example = "0.1.0-SNAPSHOT")
    String version;
}
