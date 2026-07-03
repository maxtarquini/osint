package it.osint.raven.workflow;

import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

/**
 * Typed value produced by a workflow node and stored in the shared context.
 *
 * @param id stable artifact identifier
 * @param type declared artifact type
 * @param value artifact value
 * @param producedBy node or agent that produced the artifact
 * @param producedAt artifact creation timestamp
 */
public record WorkflowArtifact(
        String id,
        Class<?> type,
        Object value,
        String producedBy,
        Instant producedAt
) implements Serializable {

    /**
     * Creates an artifact with deterministic defaults for id and timestamp.
     */
    public WorkflowArtifact {
        id = id == null || id.isBlank() ? UUID.randomUUID().toString() : id;
        type = Objects.requireNonNull(type, "type must not be null");
        value = Objects.requireNonNull(value, "value must not be null");
        producedAt = producedAt == null ? Instant.now() : producedAt;
    }
}
