from __future__ import annotations

from state import TerminalState
from runtime.modes import RuntimeMode
from runtime.kernel import RuntimeKernel
from task_plan.models import (
    TaskItemStatus,
    TaskPlanStatus,
)
from task_executor.models import (
    WorkflowStatus,
)


def validate_workspace_invariance(state: TerminalState) -> None:
    """
    Validate I10: Workspace root must remain immutable for the run.

    Called at stable graph boundaries (after planner, after critic, after concurrent execution, before output).
    Does not validate transient intermediate states.
    """
    runtime_state = state.get("runtime_state")
    if runtime_state is None:
        return

    metadata = runtime_state.metadata
    anchored_workspace = metadata.get("workspace_root")
    current_workspace = state.get("workspace")

    if anchored_workspace is not None and current_workspace is not None:
        if str(anchored_workspace) != str(current_workspace):
            raise RuntimeError(
                "Workspace root changed between steps: "
                f"anchored='{anchored_workspace}' "
                f"current='{current_workspace}'"
            )


def validate_runtime_consistency(
    state: TerminalState,
) -> None:
    """
    Validate consistency between RuntimeState, TaskPlan,
    current TaskItem, and ExecutionWorkflow.

    This function performs validation only.
    It does not mutate state.
    """

    runtime_state = state.get("runtime_state")
    task_plan = state.get("task_plan")
    workflow = state.get("execution_workflow")

    metadata = runtime_state.metadata

    # I10: Workspace root must remain immutable for the run.
    validate_workspace_invariance(state)

    # FINISHED mode: allow terminal states with recognized termination reasons
    termination_reason = metadata.get("termination_reason")

    if runtime_state.mode == RuntimeMode.FINISHED:
        # Whitelist for termination reasons that may exist in FINISHED
        # with non-COMPLETED task plan
        allowed_incomplete_termination = {
            RuntimeKernel.TERMINAL_REASON_BUDGET_EXHAUSTED,
            RuntimeKernel.TERMINAL_REASON_GOAL_COMPLETION_REJECTED,
            RuntimeKernel.TERMINAL_REASON_PARTIAL_COMPLETION,
        }
        if termination_reason in allowed_incomplete_termination:
            # Partial/incomplete termination is valid - skip plan completion check
            pass
        elif task_plan.status != TaskPlanStatus.COMPLETED:
            raise RuntimeError(
                "Runtime is FINISHED but TaskPlan is not COMPLETED."
            )

    # ----------------------------------------------------------
    # No TaskPlan yet.
    #
    # This is valid during initialization/planning.
    # ----------------------------------------------------------

    if task_plan is None:

        if runtime_state.mode == RuntimeMode.EXECUTING:
            raise RuntimeError(
                "Runtime is EXECUTING but no TaskPlan exists."
            )

        if runtime_state.mode == RuntimeMode.FINISHED:
            raise RuntimeError(
                "Runtime is FINISHED but no TaskPlan exists."
            )

        return

    in_progress_tasks = [
        task
        for task in task_plan.tasks
        if task.status == TaskItemStatus.IN_PROGRESS
    ]

    concurrent_execution = bool(
        state.get("concurrent_execution", True)
    )

    # Concurrent execution admits a dependency-ready wave, so
    # multiple task objectives may legitimately be IN_PROGRESS.
    if not concurrent_execution and len(in_progress_tasks) > 1:
        raise RuntimeError("TaskPlan contains multiple IN_PROGRESS tasks.")

    current_task = in_progress_tasks[0] if in_progress_tasks else None

    # ----------------------------------------------------------
    # EXECUTING requires an active task.
    # ----------------------------------------------------------

    if runtime_state.mode == RuntimeMode.EXECUTING:

        if current_task is None:
            raise RuntimeError(
                "Runtime is EXECUTING but TaskPlan has no "
                "IN_PROGRESS task."
            )

    # ----------------------------------------------------------
    # Workflow requires an active task.
    # ----------------------------------------------------------

    if workflow is not None and (
        not concurrent_execution or len(in_progress_tasks) == 1
    ):

        if current_task is None:
            raise RuntimeError(
                "ExecutionWorkflow exists but TaskPlan has "
                "no IN_PROGRESS task."
            )

        # ------------------------------------------------------
        # Workflow must belong to the current objective.
        # ------------------------------------------------------

        if workflow.objective != current_task.objective:
            raise RuntimeError(
                "ExecutionWorkflow objective does not match "
                "the current TaskPlan objective."
            )

    # ----------------------------------------------------------
    # EXECUTING cannot retain a completed workflow.
    # ----------------------------------------------------------

    if (
        runtime_state.mode == RuntimeMode.EXECUTING
        and workflow is not None
        and workflow.status == WorkflowStatus.COMPLETED
    ):
        raise RuntimeError(
            "Runtime is EXECUTING but the ExecutionWorkflow "
            "is already COMPLETED."
        )

    # ----------------------------------------------------------
    # FINISHED requires a completed TaskPlan (unless terminated with reason).
    # ----------------------------------------------------------

    if runtime_state.mode == RuntimeMode.FINISHED:

        if task_plan.status != TaskPlanStatus.COMPLETED:
            # Already checked above for allowed incomplete termination
            pass
