package it.osint.raven.workflow.registry;

import it.osint.raven.workflow.WorkflowCapability;
import it.osint.raven.workflow.WorkflowNode;
import it.osint.raven.workflow.agent.WorkflowAgent;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/**
 * Default in-memory {@link WorkflowRegistry} implementation.
 * <p>
 * The implementation preserves registration order, rejects duplicate node or
 * agent ids, and performs capability lookups by delegating to
 * {@link WorkflowCapability#matches(WorkflowCapability)}.
 */
final class InMemoryWorkflowRegistry implements WorkflowRegistry {

    private final Map<String, WorkflowNode> nodes = new LinkedHashMap<>();
    private final Map<String, WorkflowAgent> agents = new LinkedHashMap<>();

    @Override
    public synchronized WorkflowRegistry registerNode(WorkflowNode node) {
        Objects.requireNonNull(node, "node must not be null");
        String id = requireId(node.id(), "node");
        if (nodes.containsKey(id)) {
            throw new IllegalArgumentException("Duplicate workflow node id: " + id);
        }
        nodes.put(id, node);
        return this;
    }

    @Override
    public synchronized WorkflowRegistry registerAgent(WorkflowAgent agent) {
        Objects.requireNonNull(agent, "agent must not be null");
        String id = requireId(agent.id(), "agent");
        if (agents.containsKey(id)) {
            throw new IllegalArgumentException("Duplicate workflow agent id: " + id);
        }
        agents.put(id, agent);
        return this;
    }

    @Override
    public synchronized Optional<WorkflowNode> findNode(String id) {
        if (id == null || id.isBlank()) {
            return Optional.empty();
        }
        return Optional.ofNullable(nodes.get(id.trim()));
    }

    @Override
    public synchronized Optional<WorkflowAgent> findAgent(String id) {
        if (id == null || id.isBlank()) {
            return Optional.empty();
        }
        return Optional.ofNullable(agents.get(id.trim()));
    }

    @Override
    public synchronized List<WorkflowNode> findNodesProducing(WorkflowCapability capability) {
        Objects.requireNonNull(capability, "capability must not be null");
        return nodes.values().stream()
                .filter(node -> node.produces().stream().anyMatch(produced -> produced.matches(capability)))
                .toList();
    }

    @Override
    public synchronized List<WorkflowNode> findNodesRequiring(WorkflowCapability capability) {
        Objects.requireNonNull(capability, "capability must not be null");
        return nodes.values().stream()
                .filter(node -> node.requires().stream().anyMatch(required -> required.matches(capability)))
                .toList();
    }

    @Override
    public synchronized List<WorkflowNode> nodes() {
        return List.copyOf(nodes.values());
    }

    @Override
    public synchronized List<WorkflowAgent> agents() {
        return List.copyOf(agents.values());
    }

    private static String requireId(String id, String component) {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("workflow " + component + " id must not be blank");
        }
        return id.trim();
    }
}
