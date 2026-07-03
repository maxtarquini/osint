package it.osint.raven.workflow;

import java.io.Serializable;
import java.time.Instant;
import java.util.Objects;

/**
 * Serializable error captured during workflow execution.
 * <p>
 * The {@code exception} field stores the exception class name instead of the
 * exception instance to keep the context portable and safe to persist.
 *
 * @param node node or agent where the error occurred
 * @param exception exception class name, when available
 * @param message human-readable error message
 * @param timestamp error timestamp
 */
public record WorkflowError(
        String node,
        String exception,
        String message,
        Instant timestamp
) implements Serializable {

    /**
     * Creates a workflow error and fills a missing timestamp with the current instant.
     */
    public WorkflowError {
        timestamp = timestamp == null ? Instant.now() : timestamp;
    }

    /**
     * Builds a serializable workflow error from a thrown exception.
     *
     * @param node node or agent where the exception occurred
     * @param throwable exception to describe
     * @return serializable workflow error
     */
    public static WorkflowError from(String node, Throwable throwable) {
        Objects.requireNonNull(throwable, "throwable must not be null");
        return new WorkflowError(
                node,
                throwable.getClass().getName(),
                throwable.getMessage(),
                Instant.now()
        );
    }
}
