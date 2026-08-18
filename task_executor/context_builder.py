from __future__ import annotations

import json
from typing import Any

from agents.terminal.models import (
    ActiveTaskMemory,
    ArtifactReference,
    ExecutionMemory,
)
from agents.terminal.state import TerminalState
from agents.terminal.task_executor.models import ExecutionContext
from agents.terminal.task_plan.manager import TaskPlanManager
from agents.terminal.task_plan.models import (
    TaskItem,
    TaskItemStatus,
    TaskPlan,
)
from agents.terminal.utils.capability_selector import get_candidate_tools
from agents.terminal.utils.memory_formatter import (
    format_active_memory,
    format_artifact_catalog,
    format_execution_summary,
)
from agents.terminal.utils.tool_prompt_builder import (
    build_capability_prompt,
)


def build_execution_context(
    state: dict[str, Any],
) -> ExecutionContext:
    """
    Build the structured context consumed by the Task Executor.

    The Executor receives only the task it currently owns.

    Task ownership is resolved in this order:

    1. IN_PROGRESS task
       The Executor is continuing or regenerating a workflow
       for the task that is already being executed.

    2. Next executable task
       No task is currently active, so the Executor selects the
       next READY/PENDING task that can be started.

    Runtime decision context is included when the Executor is
    being invoked because of a previous runtime/Critic decision.
    """

    task_plan = state.get("task_plan")

    if task_plan is None:
        raise ValueError(
            "Cannot build execution context without a TaskPlan."
        )

    # ----------------------------------------------------------
    # 1. Existing active task
    #
    # CONTINUE_TASK may intentionally return to the Executor
    # while the current TaskItem remains IN_PROGRESS.
    #
    # In that case we MUST generate the new workflow for the
    # existing task rather than looking for another executable
    # task.
    # ----------------------------------------------------------

    current_task = TaskPlanManager.get_in_progress_task(
        plan=task_plan,
    )

    # ----------------------------------------------------------
    # 2. No active task
    #
    # This is the normal path for a newly created task or a
    # RETRY_TASK that reset the previous task back to READY.
    # ----------------------------------------------------------

    if current_task is None:

        current_task = TaskPlanManager.get_current_task(
            task_plan,
        )

    # ----------------------------------------------------------
    # 3. No task available
    # ----------------------------------------------------------

    if current_task is None:
        raise ValueError(
            "Cannot build execution context because the TaskPlan "
            "has no executable or IN_PROGRESS task."
        )

    return ExecutionContext(
        task_goal=task_plan.goal,
        task_metadata=_build_task_metadata(
            task_plan=task_plan,
            task=current_task,
        ),
        objective=current_task.objective,
        decision_context=_build_decision_context(
            state,
        ),
        active_memory=_build_active_memory(
            state["active_memory"],
        ),
        execution_summary=_build_execution_summary(
            state["execution_memory"],
        ),
        artifact_catalog=_build_artifact_catalog(
            state["artifact_references"],
        ),
        capabilities=_build_capabilities(
            state,
        ),
    )


def _build_task_metadata(
    *,
    task_plan: TaskPlan,
    task: TaskItem,
) -> str:
    """
    Build compact metadata describing the current task.

    The full TaskPlan is intentionally not exposed to the Executor.
    """

    completed_dependency_ids = {
        candidate.task_id
        for candidate in task_plan.tasks
        if candidate.status == TaskItemStatus.COMPLETED
    }

    completed_dependencies = [
        dependency
        for dependency in task.dependencies
        if dependency in completed_dependency_ids
    ]

    metadata = {
        "task_id": task.task_id,
        "priority": task.priority,
        "status": task.status.value,
        "dependencies": task.dependencies,
        "completed_dependencies": completed_dependencies,
        "blockers": task.blockers,
        "success_criteria": task.success_criteria,
    }

    return json.dumps(
        metadata,
        indent=2,
        ensure_ascii=False,
    )


def _build_active_memory(
    active_memory: ActiveTaskMemory,
) -> str:
    return format_active_memory(
        active_memory,
    )


def _build_execution_summary(
    execution_memory: ExecutionMemory,
) -> str:
    return format_execution_summary(
        execution_memory,
    )


def _build_artifact_catalog(
    artifact_references: list[ArtifactReference],
) -> str:
    return format_artifact_catalog(
        artifact_references,
    )


def _build_capabilities(
    state: dict[str, Any],
) -> str:
    candidate_tools = get_candidate_tools(
        state,
    )

    return build_capability_prompt(
        candidate_tools,
    )


def _build_decision_context(
    state: dict[str, Any] | TerminalState,
) -> str:
    """
    Build the Executor-facing runtime decision context.

    This contains the rationale and evidence associated with
    the runtime decision that caused the Executor to be invoked.

    The Executor should use this information to adapt its
    execution workflow. It must not treat the context as a
    command to blindly follow.
    """

    runtime_state = state.get("runtime_state")

    if runtime_state is None:
        return "No runtime decision context available."

    decision_context = runtime_state.decision_context

    if decision_context is None:
        return "No runtime decision context available."

    lines = [
        "Rationale:",
        decision_context.rationale,
        "",
        "Evidence:",
    ]

    if decision_context.evidence:
        for evidence in decision_context.evidence:
            lines.append(
                f"- {evidence}"
            )
    else:
        lines.append("- None")

    return "\n".join(lines)