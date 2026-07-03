package it.osint.raven.workflow.compiler;

import it.osint.raven.workflow.WorkflowCapability;
import it.osint.raven.workflow.WorkflowNode;

import java.io.Serializable;
import java.util.Objects;

/**
 * Directed dependency between two selected workflow nodes.
 *
 * @param from producer node
 * @param to consumer node
 * @param capability capability required by the consumer and produced by the producer
 */
public record DependencyEdge(
        WorkflowNode from,
        WorkflowNode to,
        WorkflowCapability capability
) implements Serializable {

    public DependencyEdge {
        from = Objects.requireNonNull(from, "from must not be null");
        to = Objects.requireNonNull(to, "to must not be null");
        capability = Objects.requireNonNull(capability, "capability must not be null");
    }
}
