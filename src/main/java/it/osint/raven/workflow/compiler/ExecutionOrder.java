package it.osint.raven.workflow.compiler;

import it.osint.raven.workflow.WorkflowNode;

import java.io.Serializable;
import java.util.List;

/**
 * Topological order of selected workflow nodes.
 *
 * @param nodes nodes in executable dependency order
 */
public record ExecutionOrder(List<WorkflowNode> nodes) implements Serializable {

    public ExecutionOrder {
        nodes = nodes == null ? List.of() : List.copyOf(nodes);
    }

    /**
     * Returns node ids in execution order.
     *
     * @return ordered node ids
     */
    public List<String> nodeIds() {
        return nodes.stream().map(WorkflowNode::id).toList();
    }
}
