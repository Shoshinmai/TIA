from __future__ import annotations

from agents.terminal.memory.execution_manager import ExecutionMemoryManager
from agents.terminal.models import AttemptStatus
from agents.terminal.result_processing.state_mutator import mutate_state
from agents.terminal.runtime.events import RuntimeEvent
from agents.terminal.runtime.kernel import RuntimeKernel
from agents.terminal.runtime.models import RuntimeDecisionContext
from agents.terminal.runtime.stages import RuntimeStage
from agents.terminal.state import TerminalState
from agents.terminal.task_executor.workflow_runtime import WorkflowRuntime
from agents.terminal.task_plan.manager import TaskPlanManager


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


def execute_current_workflow_step(
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

    result = workflow_runtime.execute_next_step(
        workflow,
    )

    return {
        "execution_workflow": result["workflow"],
        "tool_result": result["tool_result"],
        "workflow_completed": result["completed"],
    }


def runtime_workflow_execution_node(
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

    result = execute_current_workflow_step(
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
            raise ValueError(
                "GOAL_COMPLETED received without a TaskPlan."
            )

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

    if event in (
        RuntimeEvent.REPLAN_REQUIRED,
        RuntimeEvent.PLAN_UPDATE_REQUIRED,
    ):
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
