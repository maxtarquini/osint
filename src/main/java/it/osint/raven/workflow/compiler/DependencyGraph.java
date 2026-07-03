package it.osint.raven.workflow.compiler;

import it.osint.raven.workflow.WorkflowNode;

import java.io.Serializable;
import java.util.List;

/**
 * Directed dependency graph produced by the workflow compiler.
 * <p>
 * Edges point from dependency producer to dependent consumer.
 *
 * @param nodes selected workflow nodes
 * @param edges directed dependency edges
 */
public record DependencyGraph(
        List<WorkflowNode> nodes,
        List<DependencyEdge> edges
) implements Serializable {

    public DependencyGraph {
        nodes = nodes == null ? List.of() : List.copyOf(nodes);
        edges = edges == null ? List.of() : List.copyOf(edges);
    }
}
