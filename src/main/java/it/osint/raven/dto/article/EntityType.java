package it.osint.raven.dto.article;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Named entity categories supported by article extraction.")
public enum EntityType {
    PERSON,
    ORGANIZATION,
    COUNTRY,
    CITY,
    REGION,
    LOCATION,
    EVENT,
    WEAPON,
    MILITARY_UNIT,
    COMPANY,
    LAW,
    AGREEMENT,
    DOCUMENT
}
