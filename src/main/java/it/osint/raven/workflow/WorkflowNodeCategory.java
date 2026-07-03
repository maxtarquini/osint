package it.osint.raven.workflow;

/**
 * High-level role of a node inside a workflow DAG.
 */
public enum WorkflowNodeCategory {

    /**
     * Acquires content or events from an external source.
     */
    CONNECTOR,

    /**
     * Converts raw content into structured workflow artifacts.
     */
    PARSER,

    /**
     * Adds deterministic derived data to existing artifacts.
     */
    ENRICHMENT,

    /**
     * Uses AI or model-driven processing to produce workflow artifacts.
     */
    AI,

    /**
     * Persists workflow artifacts or execution results.
     */
    PERSISTENCE,

    /**
     * Verifies inputs, outputs or workflow invariants.
     */
    VALIDATION,

    /**
     * Performs supporting workflow operations.
     */
    UTILITY,

    /**
     * Emits workflow results to an external format or destination.
     */
    EXPORT
}
