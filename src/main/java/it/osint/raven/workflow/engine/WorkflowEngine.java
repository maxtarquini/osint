package it.osint.raven.workflow.engine;

import it.osint.raven.workflow.WorkflowContext;
import it.osint.raven.workflow.compiler.ExecutionPlan;

/**
 * Engine-independent contract for executing a compiled Raven workflow plan.
 * <p>
 * Implementations consume an {@link ExecutionPlan} produced by the workflow
 * compiler and update the supplied {@link WorkflowContext}. Engines must not
 * build dependency graphs, resolve node dependencies or choose nodes; those
 * responsibilities belong to the compiler.
 */
public interface WorkflowEngine {

    /**
     * Executes the supplied plan against the shared workflow context.
     *
     * @param plan compiled workflow execution plan
     * @param context shared workflow context to enrich during execution
     * @return immutable execution result
     * @throws Exception when an engine-level failure prevents result creation
     */
    WorkflowResult execute(ExecutionPlan plan, WorkflowContext context) throws Exception;
}
