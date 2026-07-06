package it.osint.raven.dto.article;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Qualitative confidence level.")
public enum Confidence {
    VERY_LOW,
    LOW,
    MEDIUM,
    HIGH,
    VERY_HIGH
}
