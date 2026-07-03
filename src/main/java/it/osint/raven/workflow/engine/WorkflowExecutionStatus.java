package it.osint.raven.workflow.engine;

/**
 * Terminal status reported by a workflow engine execution.
 */
public enum WorkflowExecutionStatus {

    /**
     * Every planned node completed successfully.
     */
    SUCCESS,

    /**
     * At least one planned node completed and at least one node failed or was skipped.
     */
    PARTIAL_SUCCESS,

    /**
     * The plan did not produce a usable execution because nodes failed or could not run.
     */
    FAILED,

    /**
     * Execution was interrupted before reaching a normal terminal state.
     */
    CANCELLED
}
