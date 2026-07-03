package it.osint.raven.workflow;

import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;

/**
 * Immutable audit event generated during workflow execution.
 *
 * @param timestamp event timestamp
 * @param node node or agent that emitted the event
 * @param type event classification
 * @param message concise event description
 */
public record WorkflowEvent(
        Instant timestamp,
        String node,
        WorkflowEventType type,
        String message
) implements Serializable {

    /**
     * Creates a workflow event and fills a missing timestamp with the current instant.
     */
    public WorkflowEvent {
        timestamp = timestamp == null ? Instant.now() : timestamp;
        type = Objects.requireNonNull(type, "type must not be null");
    }
}
