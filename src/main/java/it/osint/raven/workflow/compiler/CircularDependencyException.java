package it.osint.raven.workflow.compiler;

import java.util.Set;

/**
 * Raised when the selected workflow nodes contain a dependency cycle.
 */
public class CircularDependencyException extends RuntimeException {

    private final Set<String> nodeIds;

    public CircularDependencyException(Set<String> nodeIds) {
        super("Circular workflow dependency detected: " + nodeIds);
        this.nodeIds = Set.copyOf(nodeIds);
    }

    public Set<String> nodeIds() {
        return nodeIds;
    }
}
