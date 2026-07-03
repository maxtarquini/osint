package it.osint.raven.workflow.compiler;

import it.osint.raven.workflow.definition.WorkflowDefinition;

import java.io.Serializable;
import java.util.Arrays;
import java.util.Objects;

/**
 * Engine-independent output of {@link WorkflowCompiler}.
 * <p>
 * An execution plan is not a LangGraph4j graph. It is Raven's compiled
 * workflow representation: definition, selected stages, dependency graph and
 * topological execution order.
 *
 * @param definition source workflow definition
 * @param stages ordered execution stages
 * @param dependencyGraph dependency graph between selected nodes
 * @param executionOrder topological execution order
 */
public record ExecutionPlan(
        WorkflowDefinition definition,
        ExecutionStage[] stages,
        DependencyGraph dependencyGraph,
        ExecutionOrder executionOrder
) implements Serializable {

    public ExecutionPlan {
        definition = Objects.requireNonNull(definition, "definition must not be null");
        stages = stages == null ? new ExecutionStage[0] : Arrays.copyOf(stages, stages.length);
        dependencyGraph = Objects.requireNonNull(dependencyGraph, "dependencyGraph must not be null");
        executionOrder = Objects.requireNonNull(executionOrder, "executionOrder must not be null");
    }

    @Override
    public ExecutionStage[] stages() {
        return Arrays.copyOf(stages, stages.length);
    }
}
