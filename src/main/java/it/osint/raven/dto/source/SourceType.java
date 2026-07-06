package it.osint.raven.dto.source;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Supported OSINT source categories.")
public enum SourceType {
    WEBSITE,
    RSS,
    SITEMAP,
    TELEGRAM,
    X,
    FACEBOOK,
    YOUTUBE,
    PDF,
    EMAIL,
    API,
    FILESYSTEM,
    DATABASE,
    MANUAL,
    DISCORD,
    MASTODON,
    BLUESKY,
    REDDIT,
    DARK_WEB,
    TOR,
    RSS_CUSTOM
}
