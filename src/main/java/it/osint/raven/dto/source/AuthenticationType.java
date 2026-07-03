package it.osint.raven.dto.source;

public enum AuthenticationType {
    NONE,
    BASIC,
    API_KEY,
    BEARER_TOKEN,
    OAUTH2,
    SESSION_COOKIE,
    CUSTOM
}
