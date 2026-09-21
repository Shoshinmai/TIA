from dataclasses import dataclass, field
from enum import Enum

from runtime.task_execution import (
    TaskExecutionResult,
)
from task_plan.models import (
    TaskItemStatus,
    TaskPlan,
)


class PlanExecutionCondition(str, Enum):
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PlanExecutionOutcome:
    """
    Plan-level snapshot describing the state reached when concurrent
    execution stops at a stable boundary.

    This object is derived from the authoritative TaskPlan and the
    task-local terminal results produced during execution.

    It does not make semantic decisions and does not mutate the plan.
    """

    plan_id: str

    condition: PlanExecutionCondition

    completed_task_ids: list[str] = field(
        default_factory=list,
    )

    failed_task_ids: list[str] = field(
        default_factory=list,
    )

    blocked_task_ids: list[str] = field(
        default_factory=list,
    )

    cancelled_task_ids: list[str] = field(
        default_factory=list,
    )

    task_results: dict[str, TaskExecutionResult] = field(
        default_factory=dict,
    )


def build_plan_execution_outcome(
    *,
    task_plan: TaskPlan,
    task_results: list[TaskExecutionResult],
) -> PlanExecutionOutcome:
    """
    Deterministically build a plan-level execution outcome.

    Classification is based on the authoritative final TaskPlan.
    TaskExecutionResults are preserved as task-local execution
    evidence for later runtime or critic processing.
    """

    completed_task_ids: list[str] = []
    failed_task_ids: list[str] = []
    blocked_task_ids: list[str] = []
    cancelled_task_ids: list[str] = []

    # ----------------------------------------------------------
    # Classify the authoritative final task states.
    # ----------------------------------------------------------

    for task in task_plan.tasks:

        if task.status == TaskItemStatus.COMPLETED:
            completed_task_ids.append(
                task.task_id,
            )

        elif task.status == TaskItemStatus.FAILED:
            failed_task_ids.append(
                task.task_id,
            )

        elif task.status == TaskItemStatus.BLOCKED:
            blocked_task_ids.append(
                task.task_id,
            )

        elif task.status == TaskItemStatus.CANCELLED:
            cancelled_task_ids.append(
                task.task_id,
            )

    # ----------------------------------------------------------
    # Determine the plan-level execution condition.
    #
    # This is intentionally deterministic. It does not decide
    # whether the overall user goal was semantically achieved.
    # That remains a future critic responsibility.
    # ----------------------------------------------------------

    if cancelled_task_ids:

        condition = PlanExecutionCondition.CANCELLED

    elif (
        not failed_task_ids
        and not blocked_task_ids
        and all(
            task.status == TaskItemStatus.COMPLETED
            for task in task_plan.tasks
        )
    ):

        condition = PlanExecutionCondition.COMPLETED

    elif completed_task_ids:

        condition = (
            PlanExecutionCondition.PARTIALLY_COMPLETED
        )

    elif blocked_task_ids and not failed_task_ids:

        condition = PlanExecutionCondition.BLOCKED

    else:

        condition = PlanExecutionCondition.FAILED

    # ----------------------------------------------------------
    # Preserve one terminal result per task.
    #
    # The latest result for a task wins if a future retry model
    # causes multiple results for the same task to be accumulated.
    # ----------------------------------------------------------

    results_by_task_id = {
        result.task_id: result
        for result in task_results
    }

    return PlanExecutionOutcome(
        plan_id=task_plan.plan_id,
        condition=condition,
        completed_task_ids=completed_task_ids,
        failed_task_ids=failed_task_ids,
        blocked_task_ids=blocked_task_ids,
        cancelled_task_ids=cancelled_task_ids,
        task_results=results_by_task_id,
    )