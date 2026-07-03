package it.osint.raven.workflow.compiler;

import it.osint.raven.workflow.WorkflowCapability;
import it.osint.raven.workflow.WorkflowNode;

import java.io.Serializable;
import java.util.Objects;
import java.util.Set;

/**
 * One ordered stage in a compiled execution plan.
 *
 * @param index one-based stage index
 * @param node workflow node selected for this stage
 * @param requires capabilities required by the node
 * @param produces capabilities produced by the node
 */
public record ExecutionStage(
        int index,
        WorkflowNode node,
        Set<WorkflowCapability> requires,
        Set<WorkflowCapability> produces
) implements Serializable {

    public ExecutionStage {
        if (index < 1) {
            throw new IllegalArgumentException("stage index must be positive");
        }
        node = Objects.requireNonNull(node, "node must not be null");
        requires = requires == null ? Set.of() : Set.copyOf(requires);
        produces = produces == null ? Set.of() : Set.copyOf(produces);
    }
}
