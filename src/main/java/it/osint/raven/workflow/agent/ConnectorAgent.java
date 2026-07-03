package it.osint.raven.workflow.agent;

/**
 * Specialization for agents that acquire data from external sources.
 * <p>
 * Connector agents still remain plain domain contracts: they do not expose
 * HTTP clients, repositories, Spring services or persistence drivers. Concrete
 * infrastructure can be supplied by adapters outside the workflow domain.
 */
public interface ConnectorAgent extends WorkflowAgent {

    /**
     * Connector agents acquire data, so their default type is
     * {@link WorkflowAgentType#CONNECTOR}.
     *
     * @return connector agent type
     */
    @Override
    default WorkflowAgentType type() {
        return WorkflowAgentType.CONNECTOR;
    }
}
