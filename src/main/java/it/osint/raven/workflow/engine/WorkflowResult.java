package it.osint.raven.workflow.engine;

import it.osint.raven.workflow.WorkflowContext;
import it.osint.raven.workflow.compiler.ExecutionPlan;

import java.io.Serializable;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Immutable summary of one workflow engine execution.
 *
 * @param plan compiled plan that was executed
 * @param context final workflow context
 * @param status terminal execution status
 * @param startedAt execution start timestamp
 * @param completedAt execution completion timestamp
 * @param duration wall-clock execution duration
 * @param executedNodes node ids completed successfully
 * @param failedNodes node ids that exhausted execution attempts
 * @param skippedNodes node ids skipped because requirements were unavailable
 * @param metrics execution metrics visible at completion time
 */
public record WorkflowResult(
        ExecutionPlan plan,
        WorkflowContext context,
        WorkflowExecutionStatus status,
        Instant startedAt,
        Instant completedAt,
        Duration duration,
        List<String> executedNodes,
        List<String> failedNodes,
        List<String> skippedNodes,
        Map<String, Object> metrics
) implements Serializable {

    public WorkflowResult {
        plan = Objects.requireNonNull(plan, "plan must not be null");
        context = Objects.requireNonNull(context, "context must not be null");
        status = Objects.requireNonNull(status, "status must not be null");
        startedAt = Objects.requireNonNull(startedAt, "startedAt must not be null");
        completedAt = Objects.requireNonNull(completedAt, "completedAt must not be null");
        duration = duration == null ? Duration.ZERO : duration;
        executedNodes = executedNodes == null ? List.of() : List.copyOf(executedNodes);
        failedNodes = failedNodes == null ? List.of() : List.copyOf(failedNodes);
        skippedNodes = skippedNodes == null ? List.of() : List.copyOf(skippedNodes);
        metrics = metrics == null ? Map.of() : Map.copyOf(metrics);
    }
}
