package it.osint.raven.workflow.registry;

import it.osint.raven.workflow.WorkflowCapability;
import it.osint.raven.workflow.WorkflowNode;
import it.osint.raven.workflow.agent.WorkflowAgent;

import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.ServiceLoader;

/**
 * Central registry for engine-independent Raven workflow components.
 * <p>
 * The registry knows {@link WorkflowNode workflow nodes} and
 * {@link WorkflowAgent workflow agents}. It does not know LangGraph4j, Spring,
 * persistence clients or any concrete execution engine. Its role is discovery
 * and lookup: future compilers can use it to find nodes by id, inspect
 * producers and consumers of {@link WorkflowCapability capabilities}, and
 * assemble a workflow plan without hard-coded class references.
 */
public interface WorkflowRegistry {

    /**
     * Creates an empty mutable registry.
     *
     * @return new registry instance
     */
    static WorkflowRegistry create() {
        return new InMemoryWorkflowRegistry();
    }

    /**
     * Loads workflow nodes and agents with the context class loader.
     * <p>
     * Discovery is based on {@link ServiceLoader}. Implementations are expected
     * to be declared as providers of {@link WorkflowNode} or
     * {@link WorkflowAgent}. Spring component scanning is intentionally not
     * used here.
     *
     * @return registry populated from service providers
     */
    static WorkflowRegistry load() {
        ClassLoader classLoader = Thread.currentThread().getContextClassLoader();
        return load(classLoader == null ? WorkflowRegistry.class.getClassLoader() : classLoader);
    }

    /**
     * Loads workflow nodes and agents with a specific class loader.
     *
     * @param classLoader class loader used by {@link ServiceLoader}
     * @return registry populated from service providers
     */
    static WorkflowRegistry load(ClassLoader classLoader) {
        WorkflowRegistry registry = create();
        ServiceLoader.load(WorkflowNode.class, classLoader).forEach(registry::registerNode);
        ServiceLoader.load(WorkflowAgent.class, classLoader).forEach(registry::registerAgent);
        return registry;
    }

    /**
     * Registers a workflow node.
     *
     * @param node node to register
     * @return this registry
     * @throws IllegalArgumentException when another node with the same id is already registered
     */
    WorkflowRegistry registerNode(WorkflowNode node);

    /**
     * Registers several workflow nodes in iteration order.
     *
     * @param nodes nodes to register
     * @return this registry
     */
    default WorkflowRegistry registerNodes(Collection<? extends WorkflowNode> nodes) {
        if (nodes == null) {
            return this;
        }
        nodes.forEach(this::registerNode);
        return this;
    }

    /**
     * Registers a workflow agent.
     *
     * @param agent agent to register
     * @return this registry
     * @throws IllegalArgumentException when another agent with the same id is already registered
     */
    WorkflowRegistry registerAgent(WorkflowAgent agent);

    /**
     * Registers several workflow agents in iteration order.
     *
     * @param agents agents to register
     * @return this registry
     */
    default WorkflowRegistry registerAgents(Collection<? extends WorkflowAgent> agents) {
        if (agents == null) {
            return this;
        }
        agents.forEach(this::registerAgent);
        return this;
    }

    /**
     * Finds a node by stable id.
     *
     * @param id node id
     * @return matching node, if registered
     */
    Optional<WorkflowNode> findNode(String id);

    /**
     * Finds an agent by stable id.
     *
     * @param id agent id
     * @return matching agent, if registered
     */
    Optional<WorkflowAgent> findAgent(String id);

    /**
     * Finds nodes that declare they can produce the supplied capability.
     * <p>
     * Capability matching is nominal: namespace, id or alias, and version are
     * considered. Java value type is not the dependency identity.
     *
     * @param capability desired produced capability
     * @return registered producer nodes in registration order
     */
    List<WorkflowNode> findNodesProducing(WorkflowCapability capability);

    /**
     * Finds nodes that declare they require the supplied capability.
     * <p>
     * Capability matching is nominal: namespace, id or alias, and version are
     * considered. Java value type is not the dependency identity.
     *
     * @param capability desired required capability
     * @return registered consumer nodes in registration order
     */
    List<WorkflowNode> findNodesRequiring(WorkflowCapability capability);

    /**
     * Returns all registered nodes in registration order.
     *
     * @return immutable node list
     */
    List<WorkflowNode> nodes();

    /**
     * Returns all registered agents in registration order.
     *
     * @return immutable agent list
     */
    List<WorkflowAgent> agents();
}
