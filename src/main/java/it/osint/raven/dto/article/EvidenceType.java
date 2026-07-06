package it.osint.raven.dto.article;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Evidence source categories.")
public enum EvidenceType {
    ARTICLE_TEXT,
    QUOTE,
    LINKED_SOURCE,
    ATTACHMENT,
    IMAGE,
    EXTERNAL_REFERENCE
}
