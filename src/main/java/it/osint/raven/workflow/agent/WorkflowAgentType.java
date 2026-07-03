package it.osint.raven.workflow.agent;

/**
 * High-level classification of a Raven workflow agent.
 * <p>
 * Agent types describe the business capability exposed by an agent, not the
 * workflow node that may invoke it and not the runtime used to execute it.
 * The same type can therefore be used when an agent is called from a workflow,
 * REST endpoint, CLI command or batch process.
 */
public enum WorkflowAgentType {

    /**
     * Acquires documents, events or observations from an external source.
     */
    CONNECTOR,

    /**
     * Converts raw inputs into structured documents or intermediate artifacts.
     */
    PARSER,

    /**
     * Adds derived information to an existing document or artifact.
     */
    ENRICHMENT,

    /**
     * Assigns categories, labels or taxonomies to existing inputs.
     */
    CLASSIFICATION,

    /**
     * Extracts structured fields, entities, relations or metadata.
     */
    EXTRACTION,

    /**
     * Performs model-driven or rule-driven reasoning over existing artifacts.
     */
    REASONING,

    /**
     * Produces vector representations or embedding-related artifacts.
     */
    EMBEDDING,

    /**
     * Persists workflow artifacts or external side effects.
     */
    PERSISTENCE,

    /**
     * Exports workflow artifacts to a target format or destination.
     */
    EXPORT,

    /**
     * Validates inputs, outputs or domain invariants.
     */
    VALIDATION,

    /**
     * Provides supporting behavior that does not fit a more specific type.
     */
    UTILITY
}
