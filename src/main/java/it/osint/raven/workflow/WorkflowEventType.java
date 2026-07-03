package it.osint.raven.workflow;

/**
 * Classification of audit events emitted by workflow nodes.
 */
public enum WorkflowEventType {

    /**
     * A workflow context was created.
     */
    WORKFLOW_CREATED,

    /**
     * Workflow execution started.
     */
    WORKFLOW_STARTED,

    /**
     * A workflow node started its work.
     */
    NODE_STARTED,

    /**
     * A workflow node completed its work.
     */
    NODE_COMPLETED,

    /**
     * A workflow node failed.
     */
    NODE_FAILED,

    /**
     * A node produced or replaced a shared output artifact.
     */
    OUTPUT_PRODUCED,

    /**
     * A non-fatal warning was recorded.
     */
    WARNING,

    /**
     * A workflow error was recorded.
     */
    ERROR,

    /**
     * A metric was recorded or updated.
     */
    METRIC_RECORDED,

    /**
     * A temporary workflow variable was recorded or updated.
     */
    VARIABLE_SET,

    /**
     * The workflow status changed.
     */
    STATUS_CHANGED,

    /**
     * Workflow execution completed.
     */
    WORKFLOW_COMPLETED
}
