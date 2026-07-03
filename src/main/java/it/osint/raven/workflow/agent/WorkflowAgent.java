package it.osint.raven.workflow.agent;

import it.osint.raven.workflow.StructuredDocument;
import it.osint.raven.workflow.WorkflowContext;

import java.util.Collections;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Engine-independent business contract for reusable Raven workflow agents.
 * <p>
 * A {@code WorkflowAgent} represents business logic that receives a
 * {@link WorkflowContext}, reads the artifacts it needs, writes new artifacts,
 * events, warnings, errors or metrics back into that context, and returns the
 * enriched context to its caller.
 * <p>
 * An agent is deliberately not a workflow node. A workflow node models a step
 * inside a workflow DAG and may adapt one or more agents to workflow execution
 * rules. An agent models the reusable processing capability itself. The same
 * metadata extraction agent, for example, can be invoked by a
 * {@code MetadataWorkflowNode}, by a REST endpoint, by a CLI command or by a
 * batch job without knowing which entry point called it.
 * <p>
 * This contract is also deliberately independent from runtime and
 * infrastructure concerns. Implementations in this package must not depend on
 * Spring, LangGraph4j, LangChain4j, OpenAI clients, MongoDB, Neo4j, Qdrant or
 * the Raven workflow engine. Runtime adapters may wrap agents elsewhere, but
 * the agent itself only knows the shared {@link WorkflowContext}.
 * <p>
 * Agents do not log directly. Observable execution data should be recorded in
 * the context through events, warnings, errors and metrics. Metrics should be
 * emitted with {@link WorkflowContext#metric(String, Object)}; no dedicated
 * metrics API is introduced at the agent layer.
 */
public interface WorkflowAgent {

    /**
     * Returns a unique, stable identifier for this agent.
     *
     * @return stable agent id, for example {@code metadata-agent}
     */
    String id();

    /**
     * Returns a human-readable agent name.
     *
     * @return display name, for example {@code Metadata Extraction Agent}
     */
    String name();

    /**
     * Returns a concise description of the business capability implemented by
     * this agent.
     *
     * @return agent description
     */
    String description();

    /**
     * Returns the high-level business type of this agent.
     *
     * @return agent type
     */
    WorkflowAgentType type();

    /**
     * Declares Java artifact types that must be available in the
     * {@link WorkflowContext} before this agent can run successfully.
     * <p>
     * Workflow nodes may translate these type-level requirements into their
     * own capability model when composing a DAG. Non-workflow callers can use
     * the same metadata for validation or discovery without depending on the
     * workflow engine.
     *
     * @return non-null set of required artifact classes
     */
    Set<Class<?>> requires();

    /**
     * Declares Java artifact types that this agent may add to the
     * {@link WorkflowContext}.
     *
     * @return non-null set of produced artifact classes
     */
    Set<Class<?>> produces();

    /**
     * Checks whether this agent supports the supplied structured document.
     * <p>
     * Implementations can narrow support to specific document DTOs such as an
     * article, PDF document or image document. The default is intentionally
     * permissive so context-only agents, connector agents and generic utility
     * agents can be used without a structured document.
     *
     * @param document structured document to inspect, possibly null
     * @return true when this agent can process the supplied document
     */
    default boolean supports(StructuredDocument document) {
        return true;
    }

    /**
     * Executes this agent using the supplied shared context.
     * <p>
     * Implementations should read inputs through the context, store outputs
     * with producer provenance when possible, and return the enriched context.
     * The caller may be a workflow node, REST endpoint, CLI command or batch
     * runner; the agent must not depend on that caller.
     *
     * @param context shared workflow context
     * @return context enriched with this agent's outputs
     * @throws Exception when agent execution fails
     */
    WorkflowContext execute(WorkflowContext context) throws Exception;

    /**
     * Returns safe, non-secret configuration metadata exposed by this agent.
     *
     * @return immutable empty map by default
     */
    default Map<String, Object> configuration() {
        return Collections.emptyMap();
    }

    /**
     * Indicates whether this agent uses AI or model-driven inference.
     *
     * @return false by default
     */
    default boolean aiPowered() {
        return false;
    }

    /**
     * Indicates whether repeated execution with the same context is expected
     * to produce the same result, excluding timestamps and observability data.
     *
     * @return true by default
     */
    default boolean deterministic() {
        return true;
    }

    /**
     * Returns the version of this agent contract or implementation.
     *
     * @return {@code 1.0} by default
     */
    default String version() {
        return "1.0";
    }

    /**
     * Returns the model name used by AI-powered agents.
     *
     * @return empty for deterministic and non-AI agents by default
     */
    default Optional<String> modelName() {
        return Optional.empty();
    }

    /**
     * Returns the identifier of the prompt registered for this agent.
     * <p>
     * Prompt templates are intentionally not modeled yet. This hook only
     * reserves a stable reference point for future prompt registries.
     *
     * @return empty by default
     */
    default Optional<String> promptId() {
        return Optional.empty();
    }

    /**
     * Optional lifecycle hook invoked before execution.
     *
     * @param context shared workflow context
     */
    default void beforeExecute(WorkflowContext context) {
    }

    /**
     * Optional lifecycle hook invoked after successful execution.
     *
     * @param context shared workflow context
     */
    default void afterExecute(WorkflowContext context) {
    }

    /**
     * Optional lifecycle hook invoked when execution fails.
     *
     * @param context shared workflow context
     * @param ex execution exception
     */
    default void onError(WorkflowContext context, Exception ex) {
    }
}
