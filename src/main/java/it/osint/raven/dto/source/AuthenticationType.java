package it.osint.raven.dto.source;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Supported source authentication mechanisms.")
public enum AuthenticationType {
    NONE,
    BASIC,
    API_KEY,
    BEARER_TOKEN,
    OAUTH2,
    SESSION_COOKIE,
    CUSTOM
}
