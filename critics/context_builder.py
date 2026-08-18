from typing import Any

from agents.terminal.critics.models import CriticContext

from agents.terminal.runtime.events import RuntimeEvent
from agents.terminal.state import TerminalState
from agents.terminal.task_plan.manager import (
    TaskPlanManager,
)

from agents.terminal.task_plan.models import TaskPlan
from agents.terminal.utils.memory_formatter import (
    format_active_memory,
    format_artifact_catalog,
    format_execution_summary,
)


def build_critic_context(
    state: dict[str, Any] | TerminalState,
) -> CriticContext:
    """
    Build the complete context supplied to the Critic.

    The Critic receives a relevant, formatted view of the
    current runtime state rather than the raw internal objects.

    Responsibilities:
        - Resolve the current task from the TaskPlan.
        - Format remaining objectives.
        - Format execution history and current workflow state.
        - Format Active Task Memory.
        - Format artifact references.

    This function does not:
        - perform Critic reasoning,
        - modify the TaskPlan,
        - modify the ExecutionWorkflow,
        - execute tools,
        - perform runtime routing.
    """

    task_plan = state.get("task_plan")

    if task_plan is None:
        raise ValueError("Cannot build CriticContext without a TaskPlan.")

    runtime_state = state.get(
        "runtime_state",
    )

    current_task = TaskPlanManager.get_in_progress_task(
        plan=task_plan,
    )
    # ----------------------------------------------------------
    # Plan exhaustion review
    # ----------------------------------------------------------

    if (
        runtime_state is not None
        and runtime_state.last_event == RuntimeEvent.PLAN_EXHAUSTED
    ):

        return CriticContext(
            overall_goal=task_plan.goal,
            current_objective=(
                "All planned objectives have been completed. "
                "Determine whether the overall user goal has "
                "actually been achieved."
            ),
            remaining_objectives=("No remaining objectives."),
            execution_summary=_build_execution_summary(
                state,
            ),
            active_memory=format_active_memory(
                active_memory=state["active_memory"],
            ),
            artifact_catalog=format_artifact_catalog(
                state.get(
                    "artifact_references",
                    [],
                )
            ),
        )

    if current_task is None:
        raise ValueError(
            "Cannot build CriticContext because the TaskPlan "
            "has no IN_PROGRESS task."
        )

    return CriticContext(
        overall_goal=task_plan.goal,
        current_objective=current_task.objective,
        remaining_objectives=_build_remaining_objectives(
            task_plan=task_plan,
            current_task_id=current_task.task_id,
        ),
        execution_summary=_build_execution_summary(
            state,
        ),
        active_memory=format_active_memory(
            active_memory=state["active_memory"],
        ),
        artifact_catalog=format_artifact_catalog(
            state.get("artifact_references", []),
        ),
    )


def _build_remaining_objectives(
    *,
    task_plan: Any | TaskPlan,
    current_task_id: str,
) -> str:
    """
    Build a compact Critic-facing representation of the
    objectives that remain in the TaskPlan.

    The TaskPlanManager remains responsible for lifecycle
    operations. Formatting belongs here because this is
    presentation/context construction for the Critic.
    """

    remaining_tasks = [
        task
        for task in task_plan.tasks
        if (
            task.task_id != current_task_id
            and task.status.value
            not in {
                "completed",
                "cancelled",
            }
        )
    ]

    if not remaining_tasks:
        return "No remaining objectives."

    lines = []

    for index, task in enumerate(
        remaining_tasks,
        start=1,
    ):
        lines.append(f"{index}. {task.objective}")

    return "\n".join(lines)


def _build_execution_summary(
    state: dict[str, Any] | TerminalState,
) -> str:
    """
    Build the Critic-facing execution summary.

    Existing execution memory remains the primary source
    of execution history. The current ExecutionWorkflow is
    appended as the current tactical execution state.
    """

    summary = format_execution_summary(
        state["execution_memory"],
    )

    workflow = state.get("execution_workflow")

    if workflow is None:
        return summary

    workflow_lines = [
        "",
        "CURRENT EXECUTION WORKFLOW",
        "---------------------------",
        f"Workflow ID: {workflow.workflow_id}",
        f"Workflow Objective: {workflow.objective}",
        f"Workflow Strategy: {workflow.execution_strategy}",
        f"Workflow Status: {workflow.status.value}",
    ]

    if workflow.steps:
        workflow_lines.append("")
        workflow_lines.append("Workflow Steps:")

        for index, step in enumerate(
            workflow.steps,
            start=1,
        ):
            workflow_lines.append(f"{index}. {step.description}")
            workflow_lines.append(f"   Capability: {step.capability}")
            workflow_lines.append(f"   Status: {step.status.value}")

    return summary + "\n" + "\n".join(workflow_lines)
