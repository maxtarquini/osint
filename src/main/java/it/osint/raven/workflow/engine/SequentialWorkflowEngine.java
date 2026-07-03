package it.osint.raven.workflow.engine;

import it.osint.raven.workflow.WorkflowContext;
import it.osint.raven.workflow.WorkflowEventType;
import it.osint.raven.workflow.WorkflowNode;
import it.osint.raven.workflow.WorkflowStatus;
import it.osint.raven.workflow.compiler.ExecutionPlan;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.TimeoutException;

/**
 * Reference workflow engine that executes compiled plan nodes sequentially.
 * <p>
 * This implementation deliberately avoids LangGraph4j, Spring and persistence
 * dependencies. It follows the execution order already computed by
 * {@link it.osint.raven.workflow.compiler.WorkflowCompiler} and performs only
 * runtime concerns: lifecycle hooks, retry policy, timeout checks and result
 * assembly.
 */
public final class SequentialWorkflowEngine implements WorkflowEngine {

    @Override
    public WorkflowResult execute(ExecutionPlan plan, WorkflowContext context) {
        Objects.requireNonNull(plan, "plan must not be null");
        Objects.requireNonNull(context, "context must not be null");

        Instant startedAt = Instant.now();
        List<String> executedNodes = new ArrayList<>();
        List<String> failedNodes = new ArrayList<>();
        List<String> skippedNodes = new ArrayList<>();
        WorkflowExecutionStatus status = WorkflowExecutionStatus.SUCCESS;

        WorkflowContext currentContext = context;
        currentContext.status(WorkflowStatus.RUNNING)
                .event("workflow-engine", WorkflowEventType.WORKFLOW_STARTED, "Workflow execution started");

        for (WorkflowNode node : plan.executionOrder().nodes()) {
            if (Thread.currentThread().isInterrupted()) {
                status = WorkflowExecutionStatus.CANCELLED;
                break;
            }
            if (!node.canExecute(currentContext)) {
                skippedNodes.add(node.id());
                currentContext.warning("Workflow node skipped: " + node.id());
                continue;
            }
            NodeExecution nodeExecution = executeNode(node, currentContext);
            currentContext = nodeExecution.context();
            if (nodeExecution.completed()) {
                executedNodes.add(node.id());
            } else {
                failedNodes.add(node.id());
            }
            if (Thread.currentThread().isInterrupted()) {
                status = WorkflowExecutionStatus.CANCELLED;
                break;
            }
        }

        if (status != WorkflowExecutionStatus.CANCELLED) {
            status = resolveStatus(executedNodes, failedNodes, skippedNodes, plan.executionOrder().nodes().size());
        }
        currentContext.metric("workflow.executedNodes", executedNodes.size())
                .metric("workflow.failedNodes", failedNodes.size())
                .metric("workflow.skippedNodes", skippedNodes.size())
                .status(toContextStatus(status))
                .event("workflow-engine", WorkflowEventType.WORKFLOW_COMPLETED,
                        "Workflow execution completed with status " + status);

        Instant completedAt = Instant.now();
        return new WorkflowResult(
                plan,
                currentContext,
                status,
                startedAt,
                completedAt,
                Duration.between(startedAt, completedAt),
                executedNodes,
                failedNodes,
                skippedNodes,
                Map.copyOf(currentContext.getMetrics())
        );
    }

    private NodeExecution executeNode(WorkflowNode node, WorkflowContext context) {
        WorkflowContext currentContext = context;
        int attempts = allowedAttempts(node);
        for (int attempt = 1; attempt <= attempts; attempt++) {
            try {
                currentContext.event(node.id(), WorkflowEventType.NODE_STARTED,
                        "Node execution started, attempt " + attempt);
                currentContext = executeAttempt(node, currentContext);
                currentContext.event(node.id(), WorkflowEventType.NODE_COMPLETED,
                        "Node execution completed, attempt " + attempt);
                return new NodeExecution(true, currentContext);
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                recordFailure(node, currentContext, ex, attempt);
                return new NodeExecution(false, currentContext);
            } catch (Exception ex) {
                recordFailure(node, currentContext, ex, attempt);
                if (!shouldRetry(node, attempt, attempts)) {
                    return new NodeExecution(false, currentContext);
                }
            }
        }
        return new NodeExecution(false, currentContext);
    }

    private WorkflowContext executeAttempt(WorkflowNode node, WorkflowContext context) throws Exception {
        Instant nodeStartedAt = Instant.now();
        node.beforeExecute(context);
        WorkflowContext updated = node.execute(context);
        if (updated == null) {
            throw new IllegalStateException("node returned null workflow context");
        }
        node.afterExecute(updated);
        Duration elapsed = Duration.between(nodeStartedAt, Instant.now());
        Duration timeout = Objects.requireNonNull(node.timeout(), "node timeout must not be null");
        if (elapsed.compareTo(timeout) > 0) {
            throw new TimeoutException("node exceeded timeout: " + node.id());
        }
        updated.metric("workflow.node." + node.id() + ".durationMillis", elapsed.toMillis());
        return updated;
    }

    private void recordFailure(WorkflowNode node, WorkflowContext context, Exception ex, int attempt) {
        node.onError(context, ex);
        context.error(node.id(), ex)
                .event(node.id(), WorkflowEventType.NODE_FAILED,
                        "Node execution failed, attempt " + attempt);
    }

    private int allowedAttempts(WorkflowNode node) {
        if (!node.idempotent()) {
            return 1;
        }
        return Math.max(0, node.maxRetries()) + 1;
    }

    private boolean shouldRetry(WorkflowNode node, int attempt, int attempts) {
        return node.idempotent() && attempt < attempts;
    }

    private WorkflowExecutionStatus resolveStatus(
            List<String> executedNodes,
            List<String> failedNodes,
            List<String> skippedNodes,
            int plannedNodes
    ) {
        if (failedNodes.isEmpty() && skippedNodes.isEmpty()) {
            return WorkflowExecutionStatus.SUCCESS;
        }
        if (!executedNodes.isEmpty() && executedNodes.size() < plannedNodes) {
            return WorkflowExecutionStatus.PARTIAL_SUCCESS;
        }
        return WorkflowExecutionStatus.FAILED;
    }

    private WorkflowStatus toContextStatus(WorkflowExecutionStatus status) {
        return switch (status) {
            case SUCCESS -> WorkflowStatus.COMPLETED;
            case PARTIAL_SUCCESS -> WorkflowStatus.PARTIAL;
            case FAILED, CANCELLED -> WorkflowStatus.FAILED;
        };
    }

    private record NodeExecution(boolean completed, WorkflowContext context) {
    }
}
