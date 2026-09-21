from __future__ import annotations

from memory.execution_manager import ExecutionMemoryManager
from models import AttemptStatus
from result_processing.state_mutator import mutate_state
from runtime.events import RuntimeEvent
from runtime.kernel import RuntimeKernel
from runtime.models import RuntimeDecisionContext
from runtime.stages import RuntimeStage
from state import TerminalState
from task_executor.workflow_runtime import WorkflowRuntime
from task_plan.manager import TaskPlanManager
from task_plan.models import TaskItemStatus


def runtime_planner_result_node(
    state: TerminalState,
) -> dict:
    """
    Convert a successful Planner result into a RuntimeEvent.

    The Planner itself remains responsible only for producing a
    TaskPlan. Runtime orchestration happens here through the
    Runtime Kernel.
    """

    runtime_state = state["runtime_state"]

    previous_event = runtime_state.last_event

    if previous_event in (
        RuntimeEvent.PLAN_UPDATE_REQUIRED,
        RuntimeEvent.REPLAN_REQUIRED,
    ):
        event = RuntimeEvent.PLAN_UPDATED

    else:
        event = RuntimeEvent.PLAN_CREATED

    RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=event,
    )

    return {
        "runtime_state": runtime_state,
    }


async def execute_current_workflow_step(
    state: TerminalState,
) -> dict:
    """
    Execute exactly one step of the current ExecutionWorkflow.
    """

    workflow = state.get("execution_workflow")

    if workflow is None:
        raise ValueError(
            "Cannot execute workflow because no "
            "ExecutionWorkflow exists in TerminalState."
        )

    workflow_runtime = WorkflowRuntime()

    result = await workflow_runtime.execute_next_step(
        workflow,
    )

    return {
        "execution_workflow": result["workflow"],
        "tool_result": result["tool_result"],
        "workflow_completed": result["completed"],
    }


async def runtime_workflow_execution_node(
    state: TerminalState,
) -> dict:
    """
    Execute one step of the current ExecutionWorkflow.

    WorkflowRuntime executes the tactical step and returns the
    resulting ToolMessage(s).

    The ToolMessage is placed into graph messages so that the
    existing Message Adapter / Result Processing pipeline can
    consume it.

    This node does not generate workflows.
    """

    runtime_state = state["runtime_state"]

    result = await execute_current_workflow_step(
        state,
    )

    updated_workflow = result["execution_workflow"]
    tool_result = result["tool_result"]

    update = {
        "execution_workflow": updated_workflow,
    }

    # ----------------------------------------------------------
    # Forward WorkflowRuntime tool messages into the graph
    # message stream.
    # ----------------------------------------------------------

    if isinstance(tool_result, dict):

        messages = tool_result.get(
            "messages",
            [],
        )

        if messages:
            update["messages"] = messages

    # ----------------------------------------------------------
    # Workflow is still running.
    #
    # Runtime remains EXECUTING.
    #
    # The graph will return to executor_operation_router,
    # which will detect that an ExecutionWorkflow already exists
    # and execute the next workflow step.
    # ----------------------------------------------------------

    if not result["workflow_completed"]:

        return update

    # ----------------------------------------------------------
    # Tactical workflow has completely finished.
    #
    # Only now does execution become semantically reviewable.
    # ----------------------------------------------------------

    RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=RuntimeEvent.EXECUTION_COMPLETED,
    )

    update["runtime_state"] = runtime_state

    return update


def execution_memory_finalize_node(
    state: TerminalState,
) -> dict:
    """
    Finalize the current ExecutionMemory attempt using the
    RuntimeProcessingResult.

    This node is the single completion boundary for an execution
    attempt.
    """

    processed = state.get("runtime_processing_result")

    if processed is None:
        raise ValueError(
            "Cannot finalize execution memory because "
            "RuntimeProcessingResult is missing."
        )

    ephemeral = state.get("ephemeral_execution_state")

    if ephemeral is None or ephemeral.current_attempt_id is None:
        raise ValueError(
            "Cannot finalize execution memory because "
            "there is no active execution attempt."
        )

    attempt_id = ephemeral.current_attempt_id

    attempt = ExecutionMemoryManager.current_attempt(state["execution_memory"])

    if attempt is None:
        raise ValueError(
            "Cannot finalize execution memory because "
            "ExecutionMemory contains no attempts."
        )

    # ----------------------------------------------------------
    # Re-entry protection
    #
    # If the graph reaches this node again after the attempt has
    # already been finalized, do not mutate the attempt again.
    # ----------------------------------------------------------

    if attempt.attempt_id != attempt_id:
        raise ValueError(
            "Execution attempt mismatch: "
            f"active attempt is '{attempt_id}', "
            f"but current ExecutionMemory attempt is "
            f"'{attempt.attempt_id}'."
        )

    if attempt.status != AttemptStatus.RUNNING:
        # The lifecycle was already finalized.
        #
        # Clear the ephemeral pointer and allow the graph to
        # continue instead of corrupting the execution record.
        ephemeral.current_attempt_id = None

        return {
            "execution_memory": state["execution_memory"],
            "ephemeral_execution_state": ephemeral,
        }

    execution = processed.normalized_result.execution

    ExecutionMemoryManager.finish_attempt(
        execution_memory=state["execution_memory"],
        attempt_id=attempt_id,
        runtime_result=processed,
        success=execution.success,
        error=(execution.stderr or None),
    )

    # ----------------------------------------------------------
    # Execution lifecycle is now closed.
    # ----------------------------------------------------------

    ephemeral.current_attempt_id = None

    return {
        "execution_memory": state["execution_memory"],
        "ephemeral_execution_state": ephemeral,
    }


def apply_runtime_processing_result(
    state: TerminalState,
) -> None:
    """
    Apply the RuntimeProcessingResult produced by the Result
    Processing pipeline to the structured TerminalState.

    The Result Processor remains pure. This helper owns the
    deterministic state-mutation boundary.
    """

    processing_result = state.get(
        "runtime_processing_result",
    )

    if processing_result is None:
        raise ValueError(
            "Cannot apply runtime processing result because "
            "TerminalState contains no RuntimeProcessingResult."
        )

    proposal = processing_result.memory_update

    if proposal is None:
        return

    mutate_state(
        state=state,
        proposal=proposal,
    )


def runtime_memory_update_node(
    state: TerminalState,
) -> dict:
    """
    Apply the RuntimeProcessingResult produced by the Message
    Adapter to the structured runtime memory.

    This node performs deterministic state mutation only.
    """

    apply_runtime_processing_result(
        state,
    )

    return {
        "active_memory": state["active_memory"],
        # "artifact_references": state["artifact_references"],
    }


def runtime_critic_result_node(
    state: TerminalState,
) -> dict:
    """
    Apply the RuntimeEvent produced by the Critic.

    TASK_COMPLETED first advances the TaskPlan. If the plan is
    exhausted, emit a deterministic PLAN_EXHAUSTED runtime event
    so the Critic can make the final semantic goal decision.
    """

    runtime_state = state["runtime_state"]

    runtime_event = state.get(
        "critic_runtime_event",
    )

    if runtime_event is None:
        raise ValueError("Critic did not produce a RuntimeEvent.")

    event = runtime_event.event
    decision_context = runtime_event.context

    # ==========================================================
    # CONCURRENT PLAN REVIEW
    # ==========================================================
    #
    # Concurrent execution has already:
    #
    #   - completed all active workers in the wave
    #   - reconciled their results
    #   - updated the authoritative TaskPlan
    #
    # Therefore there should be no singular IN_PROGRESS task
    # representing the whole concurrent execution.
    #
    # The Critic's target-aware decision contract is used here.
    # ==========================================================

    if state.get("plan_execution_outcome") is not None:

        return _apply_concurrent_critic_decision(
            state=state,
            event=event,
            decision_context=decision_context,
            runtime_state=runtime_state,
        )

    # ==========================================================
    # GOAL_COMPLETED
    # ==========================================================
    #
    # The Critic has semantically determined that the overall
    # user goal has been satisfied.
    #
    # This is the terminal cleanup boundary.
    #
    # Do not allow:
    #
    #   completed ExecutionWorkflow
    #   active current_attempt_id
    #   IN_PROGRESS TaskItem
    #
    # to survive into FINISHED state.
    # ==========================================================

    if event == RuntimeEvent.GOAL_COMPLETED:

        task_plan = state.get(
            "task_plan",
        )

        if task_plan is None:
            raise ValueError("GOAL_COMPLETED received without a TaskPlan.")

        # ------------------------------------------------------
        # Finalize any task that is still marked IN_PROGRESS.
        #
        # This can happen when the Critic directly determines
        # that the overall goal is satisfied rather than first
        # emitting TASK_COMPLETED for the final task.
        # ------------------------------------------------------

        current_task = TaskPlanManager.get_in_progress_task(
            plan=task_plan,
        )

        if current_task is not None:

            TaskPlanManager.complete_task(
                plan=task_plan,
                task_id=current_task.task_id,
            )

            TaskPlanManager.update_task_readiness(
                plan=task_plan,
            )

        # ------------------------------------------------------
        # The tactical workflow is no longer relevant once the
        # overall goal has been completed.
        # ------------------------------------------------------

        state["execution_workflow"] = None

        # ------------------------------------------------------
        # The execution attempt should already have been closed
        # by execution_memory_finalize_node.
        #
        # This is a defensive terminal cleanup.
        # ------------------------------------------------------

        ephemeral = state.get(
            "ephemeral_execution_state",
        )

        if ephemeral is not None:
            ephemeral.current_attempt_id = None

        # ------------------------------------------------------
        # Now transition the runtime into FINISHED.
        # ------------------------------------------------------

        RuntimeKernel.handle_event(
            runtime_state=runtime_state,
            event=RuntimeEvent.GOAL_COMPLETED,
            decision_context=decision_context,
        )

        return {
            "runtime_state": runtime_state,
            "task_plan": task_plan,
            "execution_workflow": None,
            "ephemeral_execution_state": ephemeral,
            "critic_runtime_event": None,
        }

    # ----------------------------------------------------------
    # TASK_COMPLETED
    # ----------------------------------------------------------

    if event == RuntimeEvent.TASK_COMPLETED:

        task_plan = state.get("task_plan")

        if task_plan is None:
            raise ValueError("TASK_COMPLETED received without a TaskPlan.")

        current_task = TaskPlanManager.get_in_progress_task(
            plan=task_plan,
        )

        # ------------------------------------------------------
        # SPECIAL CASE:
        #
        # PLAN_EXHAUSTED has already been reached.
        #
        # At this point there is intentionally no IN_PROGRESS
        # task. The Critic is evaluating the overall user goal,
        # not completing another TaskItem.
        #
        # A TASK_COMPLETED decision here therefore means that
        # there is no remaining work at the task level.
        # ------------------------------------------------------

        if current_task is None:

            if TaskPlanManager.is_plan_complete(
                plan=task_plan,
            ):
                RuntimeKernel.handle_event(
                    runtime_state=runtime_state,
                    event=RuntimeEvent.GOAL_COMPLETED,
                    decision_context=decision_context,
                )

                return {
                    "runtime_state": runtime_state,
                    "critic_runtime_event": None,
                    "execution_workflow": None,
                }

            # --------------------------------------------------
            # No current task, but the plan is not actually
            # complete. This is a genuine runtime inconsistency.
            # --------------------------------------------------

            raise ValueError(
                "TASK_COMPLETED received with no IN_PROGRESS task "
                "while the TaskPlan is not complete."
            )

        # ------------------------------------------------------
        # NORMAL CASE:
        #
        # A real task is currently IN_PROGRESS, so complete it.
        # ------------------------------------------------------

        completion_result = complete_current_task(
            state,
        )

        print("\n========== TASK PLAN COMPLETION ==========")
        print(f"Result: {completion_result}")

        state["execution_workflow"] = None

        # ------------------------------------------------------
        # Plan completely exhausted.
        #
        # Ask Critic to determine whether the overall user goal
        # is actually complete.
        # ------------------------------------------------------

        if completion_result == "PLAN_COMPLETE":

            RuntimeKernel.handle_event(
                runtime_state=runtime_state,
                event=RuntimeEvent.PLAN_EXHAUSTED,
            )

            return {
                "runtime_state": runtime_state,
                "critic_runtime_event": None,
                "execution_workflow": None,
            }

        # ------------------------------------------------------
        # NEXT_TASK
        #
        # The TaskPlanManager has advanced the plan and another
        # executable task now exists.
        #
        # The previous ExecutionWorkflow MUST NOT survive.
        # The next Executor invocation will create a new one.
        # ------------------------------------------------------

        # ------------------------------------------------------
        # NEXT_TASK
        #
        # TaskPlanManager has completed the previous task and
        # advanced the TaskPlan.
        #
        # A new IN_PROGRESS task now exists.
        #
        # The old workflow has been cleared.
        #
        # Runtime must return to EXECUTING so that the Executor
        # generates a NEW workflow for the new current task.
        # ------------------------------------------------------

        if completion_result == "NEXT_TASK":

            RuntimeKernel.handle_event(
                runtime_state=runtime_state,
                event=RuntimeEvent.TASK_COMPLETED,
            )

            return {
                "runtime_state": runtime_state,
                "execution_workflow": None,
                "critic_runtime_event": None,
            }

        # ------------------------------------------------------
        # Plan cannot currently make progress.
        #
        # This is a deterministic runtime fact, not a semantic
        # recovery decision.
        # ------------------------------------------------------

        if completion_result == "BLOCKED":

            RuntimeKernel.handle_event(
                runtime_state=runtime_state,
                event=RuntimeEvent.TASK_BLOCKED,
            )

            return {
                "runtime_state": runtime_state,
                "critic_runtime_event": None,
                "execution_workflow": None,
            }

        # ------------------------------------------------------
        # WAITING is an unexpected condition at this point.
        # Don't silently loop.
        # ------------------------------------------------------

        if completion_result == "WAITING":
            raise RuntimeError(
                "TaskPlan has no executable task, but no blocking "
                "condition could be determined."
            )

    # ----------------------------------------------------------
    # PLAN_UPDATE_REQUIRED / REPLAN_REQUIRED
    # ----------------------------------------------------------
    #
    # The current ExecutionWorkflow belongs to the execution
    # strategy that was just rejected by the Critic.
    #
    # Neither planning decision is allowed to carry that workflow
    # into the new planning cycle.
    #
    # The distinction is:
    #
    #   PLAN_UPDATE_REQUIRED
    #       → update the unfinished portion of the TaskPlan
    #
    #   REPLAN_REQUIRED
    #       → create a new TaskPlan
    #
    # But in BOTH cases:
    #
    #   old ExecutionWorkflow → invalid
    #
    # The Planner must not inherit a stale tactical workflow.
    # The Executor will generate a fresh workflow after planning.
    # ----------------------------------------------------------

    if event == RuntimeEvent.CONTINUE_TASK:

        # The previous concurrent execution boundary has already
        # been reviewed. Clear it before starting another execution
        # cycle so it cannot be mistaken for the new execution result.
        state["plan_execution_outcome"] = None
        state["execution_workflow"] = None

    elif event in (
        RuntimeEvent.PLAN_UPDATE_REQUIRED,
        RuntimeEvent.REPLAN_REQUIRED,
    ):

        # Preserve the PlanExecutionOutcome for the Planner.
        #
        # The Planner may need the execution evidence when deciding
        # how to update or replace the rolling TaskPlan.
        state["execution_workflow"] = None

    elif event == RuntimeEvent.RETRY_TASK:

        task_plan = state.get("task_plan")

        if task_plan is None:
            raise ValueError("RETRY_TASK received without a TaskPlan.")

        current_task = TaskPlanManager.get_in_progress_task(
            plan=task_plan,
        )

        if current_task is None:
            raise ValueError("RETRY_TASK received without an IN_PROGRESS task.")

        TaskPlanManager.retry_task(
            plan=task_plan,
            task_id=current_task.task_id,
        )

        state["execution_workflow"] = None

    else:

        raise ValueError(
            "Unsupported plan-scoped concurrent Critic event: " f"'{event.value}'."
        )

    # ----------------------------------------------------------
    # Normal Runtime decision
    # ----------------------------------------------------------

    RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=event,
        decision_context=decision_context,
    )

    return {
        "runtime_state": runtime_state,
        "critic_runtime_event": None,
        "execution_workflow": state.get("execution_workflow"),
    }


def _apply_concurrent_critic_decision(
    *,
    state: TerminalState,
    event: RuntimeEvent,
    decision_context: RuntimeDecisionContext,
    runtime_state,
) -> dict:
    """
    Apply a target-aware Critic decision to a concurrently
    executed TaskPlan.

    The Critic only recommends an action.

    This function performs deterministic runtime mutation and
    routing for the concurrent execution path.
    """

    task_plan = state.get(
        "task_plan",
    )

    if task_plan is None:
        raise ValueError("Concurrent Critic decision received without a TaskPlan.")

    scope = decision_context.decision_scope

    target_task_ids = list(
        decision_context.target_task_ids,
    )

    # ==========================================================
    # TASK-SCOPED DECISIONS
    # ==========================================================

    if scope == "task":

        if not target_task_ids:
            raise ValueError(
                f"Concurrent Critic event '{event.value}' " "requires target_task_ids."
            )

        # ------------------------------------------------------
        # Validate that all requested task IDs exist.
        # ------------------------------------------------------

        target_tasks = []

        for task_id in target_task_ids:

            task = TaskPlanManager.get_task(
                plan=task_plan,
                task_id=task_id,
            )

            target_tasks.append(
                task,
            )

        # ------------------------------------------------------
        # RETRY_TASK
        # ------------------------------------------------------

        if event == RuntimeEvent.RETRY_TASK:

            for task in target_tasks:

                TaskPlanManager.retry_failed_task(
                    plan=task_plan,
                    task_id=task.task_id,
                )

            # --------------------------------------------------
            # The previous PlanExecutionOutcome describes the
            # execution that has just been reviewed.
            #
            # It must not survive into the new execution cycle.
            # --------------------------------------------------

            state["plan_execution_outcome"] = None

            state["execution_workflow"] = None

            RuntimeKernel.handle_event(
                runtime_state=runtime_state,
                event=RuntimeEvent.RETRY_TASK,
                decision_context=decision_context,
            )

            return {
                "runtime_state": runtime_state,
                "task_plan": task_plan,
                "plan_execution_outcome": None,
                "execution_workflow": None,
                "critic_runtime_event": None,
            }

        # ------------------------------------------------------
        # TASK_COMPLETED
        # ------------------------------------------------------
        #
        # In the concurrent path, the reconciler normally has
        # already marked completed tasks. Therefore this decision
        # is treated as confirmation rather than another lifecycle
        # mutation.
        # ------------------------------------------------------

        if event == RuntimeEvent.TASK_COMPLETED:

            for task in target_tasks:

                if task.status != TaskItemStatus.COMPLETED:
                    raise ValueError(
                        "Concurrent TASK_COMPLETED decision "
                        f"targeted task '{task.task_id}', but its "
                        f"current status is '{task.status}'."
                    )

            # No TaskPlan mutation is required.

            state["plan_execution_outcome"] = None
            state["execution_workflow"] = None

            RuntimeKernel.handle_event(
                runtime_state=runtime_state,
                event=RuntimeEvent.TASK_COMPLETED,
                decision_context=decision_context,
            )

            return {
                "runtime_state": runtime_state,
                "task_plan": task_plan,
                "plan_execution_outcome": None,
                "execution_workflow": None,
                "critic_runtime_event": None,
            }

        # ------------------------------------------------------
        # CONTINUE_TASK
        # ------------------------------------------------------

        if event == RuntimeEvent.CONTINUE_TASK:

            state["plan_execution_outcome"] = None
            state["execution_workflow"] = None

            RuntimeKernel.handle_event(
                runtime_state=runtime_state,
                event=RuntimeEvent.CONTINUE_TASK,
                decision_context=decision_context,
            )

            return {
                "runtime_state": runtime_state,
                "task_plan": task_plan,
                "plan_execution_outcome": None,
                "execution_workflow": None,
                "critic_runtime_event": None,
            }

        raise ValueError(
            "Unsupported task-scoped concurrent Critic event: " f"'{event.value}'."
        )

    # ==========================================================
    # PLAN-SCOPED DECISIONS
    # ==========================================================

    if scope == "plan":

        if target_task_ids:
            raise ValueError(
                f"Concurrent Critic event '{event.value}' "
                "must not contain target_task_ids."
            )

        if event == RuntimeEvent.CONTINUE_TASK:

            state["plan_execution_outcome"] = None
            state["execution_workflow"] = None

            RuntimeKernel.handle_event(
                runtime_state=runtime_state,
                event=RuntimeEvent.CONTINUE_TASK,
                decision_context=decision_context,
            )

            return {
                "runtime_state": runtime_state,
                "task_plan": task_plan,
                "plan_execution_outcome": None,
                "execution_workflow": None,
                "critic_runtime_event": None,
            }

        if event in (
            RuntimeEvent.PLAN_UPDATE_REQUIRED,
            RuntimeEvent.REPLAN_REQUIRED,
        ):

            state["execution_workflow"] = None

            RuntimeKernel.handle_event(
                runtime_state=runtime_state,
                event=event,
                decision_context=decision_context,
            )

            return {
                "runtime_state": runtime_state,
                "task_plan": task_plan,
                "plan_execution_outcome": (state.get("plan_execution_outcome")),
                "execution_workflow": None,
                "critic_runtime_event": None,
            }

        raise ValueError(
            "Unsupported plan-scoped concurrent Critic event: " f"'{event.value}'."
        )

    # ==========================================================
    # GOAL-SCOPED DECISIONS
    # ==========================================================

    if scope == "goal":

        if target_task_ids:
            raise ValueError(
                f"Concurrent Critic event '{event.value}' "
                "must not contain target_task_ids."
            )

        if event == RuntimeEvent.GOAL_COMPLETED:

            state["execution_workflow"] = None

            ephemeral = state.get(
                "ephemeral_execution_state",
            )

            if ephemeral is not None:
                ephemeral.current_attempt_id = None

            RuntimeKernel.handle_event(
                runtime_state=runtime_state,
                event=RuntimeEvent.GOAL_COMPLETED,
                decision_context=decision_context,
            )

            return {
                "runtime_state": runtime_state,
                "task_plan": task_plan,
                "plan_execution_outcome": (
                    state.get(
                        "plan_execution_outcome",
                    )
                ),
                "execution_workflow": None,
                "ephemeral_execution_state": ephemeral,
                "critic_runtime_event": None,
            }

        raise ValueError(
            "Unsupported goal-scoped concurrent Critic event: " f"'{event.value}'."
        )

    raise ValueError("Unknown Critic decision scope: " f"'{scope}'.")


def complete_current_task(
    state: TerminalState,
) -> str:
    """
    Complete the currently executing task, update dependent-task
    readiness, and determine the resulting TaskPlan condition.
    """

    task_plan = state.get("task_plan")

    if task_plan is None:
        raise ValueError("Cannot complete a task without a TaskPlan.")

    current_task = TaskPlanManager.get_in_progress_task(
        plan=task_plan,
    )

    if current_task is None:
        raise ValueError(
            "TASK_COMPLETED received but no task is currently " "IN_PROGRESS."
        )

    TaskPlanManager.complete_task(
        plan=task_plan,
        task_id=current_task.task_id,
    )

    TaskPlanManager.update_task_readiness(
        plan=task_plan,
    )

    return evaluate_task_plan_after_completion(
        state,
    )


def runtime_stage_router(
    state: TerminalState,
) -> RuntimeStage:
    """
    Convert the current RuntimeState into the graph-level
    RuntimeStage.

    This is the only graph routing function that directly maps
    RuntimeState -> RuntimeStage.
    """

    return RuntimeKernel.current_stage(
        runtime_state=state["runtime_state"],
    )


def runtime_initialization_node(
    state: TerminalState,
) -> dict:
    """
    Convert completed task initialization into the first
    Runtime event.

    The Runtime Kernel owns the INITIALIZING -> PLANNING
    transition.
    """

    runtime_state = state["runtime_state"]

    RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=RuntimeEvent.TASK_READY,
    )

    return {
        "runtime_state": runtime_state,
    }


def evaluate_task_plan_after_completion(
    state: TerminalState,
) -> str:
    """
    Determine the deterministic TaskPlan condition after a task
    has completed.
    """

    task_plan = state.get("task_plan")

    if task_plan is None:
        raise ValueError("Cannot evaluate TaskPlan without a TaskPlan.")

    # ----------------------------------------------------------
    # 1. Every task completed
    # ----------------------------------------------------------

    if TaskPlanManager.is_plan_complete(
        plan=task_plan,
    ):
        return "PLAN_COMPLETE"

    # ----------------------------------------------------------
    # 2. Another executable task exists
    # ----------------------------------------------------------

    next_task = TaskPlanManager.get_current_task(
        task_plan,
    )

    if next_task is not None:
        return "NEXT_TASK"

    # ----------------------------------------------------------
    # 3. Remaining tasks are blocked by terminal dependencies
    # ----------------------------------------------------------

    blocked_tasks = TaskPlanManager.get_blocked_tasks(
        plan=task_plan,
    )

    if blocked_tasks:
        return "BLOCKED"

    # ----------------------------------------------------------
    # 4. No executable task and no deterministic blocker
    # ----------------------------------------------------------

    return "WAITING"
