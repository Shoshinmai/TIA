from __future__ import annotations

from agents.terminal.state import TerminalState
from agents.terminal.runtime.modes import RuntimeMode
from agents.terminal.task_plan.models import (
    TaskItemStatus,
    TaskPlanStatus,
)
from agents.terminal.task_executor.models import (
    WorkflowStatus,
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

    if runtime_state is None:
        raise ValueError(
            "Runtime consistency check requires RuntimeState."
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

    # ----------------------------------------------------------
    # Only one objective may be executing.
    # ----------------------------------------------------------

    if len(in_progress_tasks) > 1:
        raise RuntimeError(
            "TaskPlan contains multiple IN_PROGRESS tasks."
        )

    current_task = (
        in_progress_tasks[0]
        if in_progress_tasks
        else None
    )

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

    if workflow is not None:

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
    # FINISHED requires a completed TaskPlan.
    # ----------------------------------------------------------

    if runtime_state.mode == RuntimeMode.FINISHED:

        if task_plan.status != TaskPlanStatus.COMPLETED:
            raise RuntimeError(
                "Runtime is FINISHED but TaskPlan is not COMPLETED."
            )