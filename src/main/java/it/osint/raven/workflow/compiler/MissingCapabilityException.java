package it.osint.raven.workflow.compiler;

import it.osint.raven.workflow.WorkflowCapability;

/**
 * Raised when no registered node can produce a required workflow capability.
 */
public class MissingCapabilityException extends RuntimeException {

    private final WorkflowCapability capability;

    public MissingCapabilityException(WorkflowCapability capability) {
        super("Missing workflow capability producer: " + capability.qualifiedName());
        this.capability = capability;
    }

    public WorkflowCapability capability() {
        return capability;
    }
}
