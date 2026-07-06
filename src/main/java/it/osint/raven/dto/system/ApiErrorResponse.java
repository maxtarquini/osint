package it.osint.raven.dto.system;

import io.swagger.v3.oas.annotations.media.Schema;

import java.time.Instant;

@Schema(description = "Standard REST API error response.")
public record ApiErrorResponse(
        @Schema(description = "Machine-readable error code.", example = "CONFIGURATION_SAVE_FAILED")
        String code,
        @Schema(description = "Human-readable error message.", example = "Unable to save Raven configuration.")
        String message,
        @Schema(description = "Request path that produced the error.", example = "/api/system/configuration")
        String path,
        @Schema(description = "Error timestamp.")
        Instant timestamp
) {
}
