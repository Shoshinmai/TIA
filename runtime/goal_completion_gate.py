from __future__ import annotations

from dataclasses import dataclass, field

from models import ActiveTaskMemory

from runtime.plan_execution_outcome import PlanExecutionOutcome
from task_plan.models import (
    TaskItemStatus,
    TaskPlan,
    TaskPlanStatus,
)


MAX_GOAL_COMPLETION_REJECTIONS = 2


@dataclass(frozen=True)
class GoalCompletionVerdict:
    """
    Deterministic verdict for one Critic GOAL_COMPLETED claim.
    """

    accepted: bool

    reasons: list[str] = field(
        default_factory=list,
    )


def verify_goal_completion_claim(
    *,
    task_plan: TaskPlan,
    outcome: PlanExecutionOutcome | None,
    active_memory: ActiveTaskMemory | None = None,
) -> GoalCompletionVerdict:
    """
    Verify a Critic GOAL_COMPLETED claim against authoritative
    runtime state.

    The Critic owns the semantic judgment of whether the user's
    goal has been achieved. It does not own the authoritative
    lifecycle state of the TaskPlan, the plan execution outcome,
    or Active Task Memory.

    This function therefore does not judge semantics. It only
    refuses a completion claim that contradicts state the Critic
    itself was given, such as:

        - a planned objective that failed, is blocked, or was
          cancelled,
        - a criteria-bearing task that completed but was never
          confirmed by a Critic TASK_COMPLETED decision,
        - a TaskPlan that is not COMPLETED,
        - an execution boundary that produced no successful
          execution result,
        - Active Task Memory that still records unresolved needs.

    Every rejection reason is explicit so the Critic can be
    re-evaluated with the exact missing justification.
    """

    reasons: list[str] = []

    unresolved = _collect_unresolved_tasks(
        task_plan=task_plan,
        outcome=outcome,
    )

    if unresolved:
        reasons.append(
            "The plan still contains objectives that did not reach "
            "a successful terminal state: "
            + "; ".join(unresolved)
            + ". Either these objectives do not affect the user's "
            "goal and that is stated explicitly with evidence, or "
            "recovery is required."
        )

    unconfirmed = _collect_unconfirmed_tasks(
        task_plan=task_plan,
    )

    if unconfirmed:
        reasons.append(
            "These completed tasks carry success criteria but have "
            "never been confirmed by a Critic TASK_COMPLETED "
            "decision: "
            + "; ".join(unconfirmed)
            + ". Emit TASK_COMPLETED targeting each of them with "
            "affirmative evidence for their criteria, then claim "
            "GOAL_COMPLETED."
        )

    if task_plan.status != TaskPlanStatus.COMPLETED:
        reasons.append(
            "The TaskPlan status is "
            f"'{task_plan.status.value}', not 'completed'."
        )

    if outcome is not None and not outcome.completed_task_ids:
        reasons.append(
            "The execution boundary produced no successfully "
            "completed task, so no execution evidence establishes "
            "that the user's goal has been achieved."
        )

    unresolved_needs = _collect_unresolved_needs(active_memory)

    if unresolved_needs:
        reasons.append(
            "Active Task Memory still records unresolved needs: "
            + "; ".join(unresolved_needs)
            + "."
        )

    if not reasons:
        return GoalCompletionVerdict(
            accepted=True,
            reasons=[],
        )

    return GoalCompletionVerdict(
        accepted=False,
        reasons=reasons,
    )


def _collect_unresolved_tasks(
    *,
    task_plan: TaskPlan,
    outcome: PlanExecutionOutcome | None,
) -> list[str]:
    """
    Describe every task that did not complete successfully.

    Task objectives are resolved from the authoritative TaskPlan so
    the Critic is confronted with the actual work, not only an id.
    """

    if outcome is None:
        return []

    groups = (
        ("failed", outcome.failed_task_ids),
        ("blocked", outcome.blocked_task_ids),
        ("cancelled", outcome.cancelled_task_ids),
    )

    objectives = {
        task.task_id: task.objective
        for task in task_plan.tasks
    }

    unresolved: list[str] = []

    for label, task_ids in groups:

        for task_id in task_ids:

            objective = objectives.get(
                task_id,
                "",
            )

            unresolved.append(
                f"{task_id} ({label}): {objective}".rstrip(": ")
            )

    return unresolved


def _collect_unconfirmed_tasks(
    *,
    task_plan: TaskPlan,
) -> list[str]:
    """
    Describe every completed task with success criteria that the
    Critic has not explicitly confirmed.

    Confirmation is a Critic decision recorded on the TaskItem.
    Execution reaching COMPLETED never sets it.
    """

    unconfirmed: list[str] = []

    for task in task_plan.tasks:
        if task.status != TaskItemStatus.COMPLETED:
            continue

        if not task.success_criteria:
            continue

        if task.confirmed:
            continue

        unconfirmed.append(
            f"{task.task_id}: {task.objective}"
        )

    return unconfirmed


def _collect_unresolved_needs(
    active_memory: ActiveTaskMemory | None,
) -> list[str]:
    if active_memory is None:
        return []

    return [
        str(need)
        for need in active_memory.unresolved_needs
        if str(need).strip()
    ]