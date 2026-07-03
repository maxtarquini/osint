package it.osint.raven.workflow;

/**
 * Lifecycle state of a workflow execution context.
 */
public enum WorkflowStatus {

    /**
     * The context has been created but execution has not started yet.
     */
    CREATED,

    /**
     * The workflow is currently executing one or more nodes.
     */
    RUNNING,

    /**
     * The workflow completed all required processing successfully.
     */
    COMPLETED,

    /**
     * The workflow failed and cannot continue without external intervention.
     */
    FAILED,

    /**
     * The workflow produced usable results while one or more nodes failed or were skipped.
     */
    PARTIAL
}
