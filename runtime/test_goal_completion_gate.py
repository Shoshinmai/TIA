import pytest

from models import ActiveTaskMemory

from runtime.goal_completion_gate import (
    verify_goal_completion_claim,
)

from runtime.plan_execution_outcome import (
    PlanExecutionCondition,
    PlanExecutionOutcome,
)

from task_plan.models import (
    TaskItem,
    TaskItemStatus,
    TaskPlan,
    TaskPlanStatus,
)


def build_plan(
    *,
    tasks: list[TaskItem],
    status: TaskPlanStatus = TaskPlanStatus.ACTIVE,
) -> TaskPlan:
    return TaskPlan(
        plan_id="plan-1",
        goal="explain the repository layout",
        status=status,
        tasks=tasks,
    )


def build_outcome(
    *,
    completed: list[str] | None = None,
    failed: list[str] | None = None,
    blocked: list[str] | None = None,
    cancelled: list[str] | None = None,
) -> PlanExecutionOutcome:
    return PlanExecutionOutcome(
        plan_id="plan-1",
        condition=PlanExecutionCondition.PARTIALLY_COMPLETED,
        completed_task_ids=completed or [],
        failed_task_ids=failed or [],
        blocked_task_ids=blocked or [],
        cancelled_task_ids=cancelled or [],
    )


def test_completion_claim_accepted_when_plan_is_proven_complete():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Read the project README",
                status=TaskItemStatus.COMPLETED,
            )
        ],
        status=TaskPlanStatus.COMPLETED,
    )

    outcome = build_outcome(completed=["a1"])

    verdict = verify_goal_completion_claim(
        task_plan=plan,
        outcome=outcome,
    )

    assert verdict.accepted is True
    assert verdict.reasons == []


def test_completion_claim_rejected_when_a_task_failed():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Identify the core goal",
                status=TaskItemStatus.COMPLETED,
            ),
            TaskItem(
                task_id="a2",
                objective="Persist the discovered knowledge",
                status=TaskItemStatus.FAILED,
            ),
        ],
    )

    outcome = build_outcome(
        completed=["a1"],
        failed=["a2"],
    )

    verdict = verify_goal_completion_claim(
        task_plan=plan,
        outcome=outcome,
    )

    assert verdict.accepted is False
    assert any(
        "a2 (failed): Persist the discovered knowledge" in reason
        for reason in verdict.reasons
    )


def test_completion_claim_rejected_when_plan_is_not_completed():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Inspect the runtime",
                status=TaskItemStatus.READY,
            )
        ],
    )

    verdict = verify_goal_completion_claim(
        task_plan=plan,
        outcome=None,
    )

    assert verdict.accepted is False
    assert any(
        "not 'completed'" in reason
        for reason in verdict.reasons
    )


def test_completion_claim_rejected_without_any_completed_task():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Attempt the migration",
                status=TaskItemStatus.FAILED,
            )
        ],
    )

    outcome = build_outcome(failed=["a1"])

    verdict = verify_goal_completion_claim(
        task_plan=plan,
        outcome=outcome,
    )

    assert verdict.accepted is False
    assert any(
        "no successfully completed task" in reason
        for reason in verdict.reasons
    )


def test_completion_claim_rejected_while_memory_records_unresolved_needs():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Answer the user",
                status=TaskItemStatus.COMPLETED,
            )
        ],
        status=TaskPlanStatus.COMPLETED,
    )

    outcome = build_outcome(completed=["a1"])

    active_memory = ActiveTaskMemory(
        unresolved_needs=["Confirm the migration result with the user"],
    )

    verdict = verify_goal_completion_claim(
        task_plan=plan,
        outcome=outcome,
        active_memory=active_memory,
    )

    assert verdict.accepted is False
    assert any(
        "unresolved needs" in reason
        for reason in verdict.reasons
    )


def test_blocked_and_cancelled_tasks_also_block_completion():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="b1",
                objective="Apply the pending patch",
                status=TaskItemStatus.BLOCKED,
            ),
            TaskItem(
                task_id="c1",
                objective="Verify the deployment",
                status=TaskItemStatus.CANCELLED,
            ),
        ],
    )

    outcome = build_outcome(
        blocked=["b1"],
        cancelled=["c1"],
    )

    verdict = verify_goal_completion_claim(
        task_plan=plan,
        outcome=outcome,
    )

    assert verdict.accepted is False
    assert any("b1 (blocked)" in reason for reason in verdict.reasons)
    assert any("c1 (cancelled)" in reason for reason in verdict.reasons)