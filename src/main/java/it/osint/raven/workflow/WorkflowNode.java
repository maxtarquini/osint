package it.osint.raven.workflow;

import java.time.Duration;
import java.util.Collections;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Engine-independent contract implemented by every node that can participate
 * in a Raven workflow.
 * <p>
 * A node reads inputs from a {@link WorkflowContext}, enriches that same
 * context with produced artifacts, events, warnings, errors or metrics, and
 * returns the enriched context to the caller. Implementations must remain
 * independent from workflow engines, dependency-injection frameworks and
 * persistence clients.
 */
public interface WorkflowNode {

    /**
     * Returns the unique, stable node identifier used by workflow definitions.
     *
     * @return unique node id, for example {@code metadata-extractor}
     */
    String id();

    /**
     * Returns a human-readable node name.
     *
     * @return display name, for example {@code Metadata Extraction}
     */
    String name();

    /**
     * Returns a concise description of the node responsibility.
     *
     * @return node description
     */
    String description();

    /**
     * Returns the node category used for discovery and workflow composition.
     *
     * @return node category
     */
    WorkflowNodeCategory category();

    /**
     * Declares named artifact capabilities that must be present in the context
     * before this node can execute.
     *
     * @return non-null set of required capabilities
     */
    Set<WorkflowCapability> requires();

    /**
     * Declares named artifact capabilities this node may produce.
     *
     * @return non-null set of produced capabilities
     */
    Set<WorkflowCapability> produces();

    /**
     * Executes this node using the supplied shared context.
     * <p>
     * Implementations should read required inputs through
     * {@link WorkflowContext#get(WorkflowCapability)} or
     * {@link WorkflowContext#require(WorkflowCapability)} and store outputs
     * through {@link WorkflowContext#put(String, WorkflowCapability, Object)}.
     *
     * @param context shared workflow context
     * @return the same context enriched with this node's outputs
     * @throws Exception when node execution fails
     */
    WorkflowContext execute(WorkflowContext context) throws Exception;

    /**
     * Checks whether all required capabilities are available in the context.
     * <p>
     * This method intentionally delegates to
     * {@link WorkflowContext#contains(WorkflowCapability)} and does not perform
     * reflection-based dependency inspection.
     *
     * @param context shared workflow context
     * @return true when all declared requirements are present
     */
    default boolean canExecute(WorkflowContext context) {
        Objects.requireNonNull(context, "context must not be null");
        return requires().stream().allMatch(context::contains);
    }

    /**
     * Returns node configuration metadata.
     *
     * @return immutable empty map by default
     */
    default Map<String, Object> configuration() {
        return Collections.emptyMap();
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

    /**
     * Returns the maximum duration allowed for a single node execution.
     *
     * @return five minutes by default
     */
    default Duration timeout() {
        return Duration.ofMinutes(5);
    }

    /**
     * Returns the maximum number of retries after an execution failure.
     *
     * @return zero retries by default
     */
    default int maxRetries() {
        return 0;
    }

    /**
     * Indicates whether this node can be scheduled in parallel with other
     * compatible nodes.
     *
     * @return true by default
     */
    default boolean parallelizable() {
        return true;
    }

    /**
     * Indicates whether repeated execution with the same context is expected to
     * be safe for workflow recovery.
     *
     * @return true by default
     */
    default boolean idempotent() {
        return true;
    }

    /**
     * Returns node priority for choosing among equivalent nodes.
     *
     * @return priority value, where lower values can be preferred by engines
     */
    default int priority() {
        return 100;
    }
}
