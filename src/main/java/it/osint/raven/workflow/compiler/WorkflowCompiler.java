package it.osint.raven.workflow.compiler;

import it.osint.raven.workflow.WorkflowCapability;
import it.osint.raven.workflow.WorkflowNode;
import it.osint.raven.workflow.definition.WorkflowDefinition;
import it.osint.raven.workflow.definition.WorkflowGoal;
import it.osint.raven.workflow.registry.WorkflowRegistry;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Queue;
import java.util.Set;

/**
 * Compiles a declarative {@link WorkflowDefinition} into an
 * engine-independent {@link ExecutionPlan}.
 * <p>
 * This compiler does not execute a graph and does not create a LangGraph4j
 * DAG. It resolves workflow goals against a {@link WorkflowRegistry}, expands
 * missing dependency nodes, builds a dependency graph and orders the selected
 * nodes with Kahn's topological sort algorithm. Runtime-specific engines can
 * consume the resulting execution plan later.
 */
public final class WorkflowCompiler {

    /**
     * Compiles a workflow definition using the supplied registry.
     *
     * @param definition workflow definition to compile
     * @param registry registry containing available nodes and agents
     * @return engine-independent execution plan
     */
    public ExecutionPlan compile(WorkflowDefinition definition, WorkflowRegistry registry) {
        Objects.requireNonNull(definition, "definition must not be null").validate();
        Objects.requireNonNull(registry, "registry must not be null");

        CompilationState state = new CompilationState();
        definition.goals().stream()
                .sorted(Comparator.comparingInt(WorkflowGoal::priority))
                .forEach(goal -> resolveProducer(goal.capability(), registry, state));

        DependencyGraph graph = new DependencyGraph(
                List.copyOf(state.selectedNodes.values()),
                List.copyOf(state.edges)
        );
        ExecutionOrder order = new ExecutionOrder(topologicalSort(graph));
        ExecutionStage[] stages = buildStages(order.nodes());
        return new ExecutionPlan(definition, stages, graph, order);
    }

    private WorkflowNode resolveProducer(
            WorkflowCapability capability,
            WorkflowRegistry registry,
            CompilationState state
    ) {
        List<WorkflowNode> producers = registry.findNodesProducing(capability);
        if (producers.isEmpty()) {
            throw new MissingCapabilityException(capability);
        }
        if (producers.size() > 1) {
            throw new AmbiguousCapabilityException(capability, producers);
        }
        WorkflowNode producer = producers.getFirst();
        resolveNode(producer, registry, state);
        return producer;
    }

    private void resolveNode(WorkflowNode node, WorkflowRegistry registry, CompilationState state) {
        if (state.resolvedNodeIds.contains(node.id())) {
            return;
        }
        if (state.resolvingNodeIds.contains(node.id())) {
            return;
        }
        state.selectedNodes.putIfAbsent(node.id(), node);
        state.resolvingNodeIds.add(node.id());
        for (WorkflowCapability requirement : node.requires()) {
            WorkflowNode dependency = resolveProducer(requirement, registry, state);
            state.edges.add(new DependencyEdge(dependency, node, requirement));
        }
        state.resolvingNodeIds.remove(node.id());
        state.resolvedNodeIds.add(node.id());
    }

    /**
     * Kahn topological sort implementation.
     */
    private List<WorkflowNode> topologicalSort(DependencyGraph graph) {
        Map<String, WorkflowNode> nodesById = new LinkedHashMap<>();
        graph.nodes().forEach(node -> nodesById.put(node.id(), node));

        Map<String, Integer> inDegree = new LinkedHashMap<>();
        Map<String, List<String>> outgoing = new LinkedHashMap<>();
        nodesById.keySet().forEach(id -> {
            inDegree.put(id, 0);
            outgoing.put(id, new ArrayList<>());
        });

        for (DependencyEdge edge : graph.edges()) {
            String from = edge.from().id();
            String to = edge.to().id();
            if (!nodesById.containsKey(from) || !nodesById.containsKey(to)) {
                continue;
            }
            outgoing.get(from).add(to);
            inDegree.put(to, inDegree.get(to) + 1);
        }

        Queue<String> ready = new ArrayDeque<>();
        inDegree.forEach((id, degree) -> {
            if (degree == 0) {
                ready.add(id);
            }
        });

        List<WorkflowNode> ordered = new ArrayList<>();
        while (!ready.isEmpty()) {
            String id = ready.remove();
            ordered.add(nodesById.get(id));
            for (String target : outgoing.get(id)) {
                int degree = inDegree.get(target) - 1;
                inDegree.put(target, degree);
                if (degree == 0) {
                    ready.add(target);
                }
            }
        }

        if (ordered.size() != nodesById.size()) {
            Set<String> remaining = new LinkedHashSet<>();
            inDegree.forEach((id, degree) -> {
                if (degree > 0) {
                    remaining.add(id);
                }
            });
            throw new CircularDependencyException(remaining);
        }
        return List.copyOf(ordered);
    }

    private static ExecutionStage[] buildStages(List<WorkflowNode> orderedNodes) {
        ExecutionStage[] stages = new ExecutionStage[orderedNodes.size()];
        for (int index = 0; index < orderedNodes.size(); index++) {
            WorkflowNode node = orderedNodes.get(index);
            stages[index] = new ExecutionStage(index + 1, node, node.requires(), node.produces());
        }
        return stages;
    }

    private static final class CompilationState {

        private final Map<String, WorkflowNode> selectedNodes = new LinkedHashMap<>();
        private final Set<String> resolvingNodeIds = new LinkedHashSet<>();
        private final Set<String> resolvedNodeIds = new LinkedHashSet<>();
        private final Set<DependencyEdge> edges = new LinkedHashSet<>();
    }
}
