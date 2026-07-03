package it.osint.raven.workflow.agent;

/**
 * Specialization for agents implemented with deterministic algorithms.
 * <p>
 * Typical implementations include parsers, normalizers, validators,
 * deduplicators and deterministic enrichers. This interface exists to make the
 * distinction from AI-powered agents explicit while preserving the common
 * {@link WorkflowAgent} contract.
 */
public interface DeterministicAgent extends WorkflowAgent {

    /**
     * Deterministic agents are not AI-powered unless a specific implementation
     * intentionally overrides this behavior.
     *
     * @return false
     */
    @Override
    default boolean aiPowered() {
        return false;
    }

    /**
     * Deterministic agents are expected to produce stable results for the same
     * inputs.
     *
     * @return true
     */
    @Override
    default boolean deterministic() {
        return true;
    }
}
