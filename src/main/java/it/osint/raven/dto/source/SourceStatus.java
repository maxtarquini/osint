package it.osint.raven.dto.source;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Operational status of an OSINT source.")
public enum SourceStatus {
    ENABLED,
    DISABLED,
    ERROR
}
