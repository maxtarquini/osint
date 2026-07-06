package it.osint.raven.dto.article;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Semantic category of an extracted claim.")
public enum ClaimType {
    FACTUAL_ASSERTION,
    ACCUSATION,
    DENIAL,
    THREAT,
    INTENT,
    ATTRIBUTION,
    ASSESSMENT,
    QUOTE
}
