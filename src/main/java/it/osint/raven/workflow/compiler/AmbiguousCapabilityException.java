package it.osint.raven.workflow.compiler;

import it.osint.raven.workflow.WorkflowCapability;
import it.osint.raven.workflow.WorkflowNode;

import java.util.List;

/**
 * Raised when more than one registered node can produce the same capability.
 */
public class AmbiguousCapabilityException extends RuntimeException {

    private final WorkflowCapability capability;
    private final List<WorkflowNode> candidates;

    public AmbiguousCapabilityException(WorkflowCapability capability, List<WorkflowNode> candidates) {
        super("Ambiguous workflow capability producer: " + capability.qualifiedName()
                + " candidates=" + candidates.stream().map(WorkflowNode::id).toList());
        this.capability = capability;
        this.candidates = List.copyOf(candidates);
    }

    public WorkflowCapability capability() {
        return capability;
    }

    public List<WorkflowNode> candidates() {
        return candidates;
    }
}
