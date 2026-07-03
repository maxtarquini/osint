package it.osint.raven.workflow.agent;

/**
 * Specialization for agents powered by language models.
 * <p>
 * This contract does not introduce a model client, prompt template or
 * LangChain4j dependency. It only exposes metadata that lets callers discover
 * AI-powered behavior while keeping the agent independent from any inference
 * runtime.
 */
public interface LlmAgent extends WorkflowAgent {

    /**
     * LLM agents are AI-powered by definition.
     *
     * @return true
     */
    @Override
    default boolean aiPowered() {
        return true;
    }

    /**
     * LLM agents are normally non-deterministic because model sampling,
     * provider behavior or prompt evolution may change outputs.
     *
     * @return false
     */
    @Override
    default boolean deterministic() {
        return false;
    }
}
