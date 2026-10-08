import pytest

from models import PlannerTask, TaskPlanningOutput

from task_plan.materializer import TaskPlanMaterializer
from task_plan.manager import TaskPlanManager
from task_plan.models import (
    TaskItem,
    TaskItemStatus,
    TaskPlan,
    TaskPlanStatus,
)
from utils.memory_formatter import format_task_plan


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


def test_materializer_copies_success_criteria_into_runtime_task():
    planning_output = TaskPlanningOutput(
        strategy="Inspect then document",
        tasks=[
            PlannerTask(
                planner_task_id="task_1",
                objective="Document the runtime routing",
                success_criteria=[
                    "The routing table is reproduced with file references"
                ],
            )
        ],
    )

    plan = TaskPlanMaterializer.materialize(
        goal="explain the repository layout",
        planning_output=planning_output,
    )

    assert plan.tasks[0].success_criteria == [
        "The routing table is reproduced with file references"
    ]
    assert plan.tasks[0].confirmed is False


def test_materialized_task_starts_unconfirmed():
    planning_output = TaskPlanningOutput(
        strategy="Inspect then document",
        tasks=[
            PlannerTask(
                planner_task_id="task_1",
                objective="Document the runtime routing",
            )
        ],
    )

    plan = TaskPlanMaterializer.materialize(
        goal="explain the repository layout",
        planning_output=planning_output,
    )

    assert plan.tasks[0].confirmed is False


def test_confirm_task_marks_completed_task_confirmed():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Read the project README",
                status=TaskItemStatus.COMPLETED,
                success_criteria=["The README summary is recorded"],
            )
        ],
    )

    TaskPlanManager.confirm_task(
        plan=plan,
        task_id="a1",
    )

    assert plan.tasks[0].confirmed is True


def test_confirm_task_refuses_task_that_is_not_completed():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Read the project README",
                status=TaskItemStatus.READY,
                success_criteria=["The README summary is recorded"],
            )
        ],
    )

    with pytest.raises(ValueError):
        TaskPlanManager.confirm_task(
            plan=plan,
            task_id="a1",
        )

    assert plan.tasks[0].confirmed is False


def test_fail_task_clears_confirmation():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Read the project README",
                status=TaskItemStatus.COMPLETED,
                success_criteria=["The README summary is recorded"],
                confirmed=True,
            )
        ],
    )

    TaskPlanManager.fail_task(
        plan=plan,
        task_id="a1",
        reason="The recorded summary contradicted the README",
    )

    assert plan.tasks[0].confirmed is False


def test_completed_retry_clears_confirmation():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Read the project README",
                status=TaskItemStatus.COMPLETED,
                confirmed=True,
            )
        ],
    )

    TaskPlanManager.retry_completed_task(
        plan=plan,
        task_id="a1",
    )

    assert plan.tasks[0].status == TaskItemStatus.READY
    assert plan.tasks[0].confirmed is False


def test_activate_plan_marks_unfinished_plan_active():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Read the project README",
                status=TaskItemStatus.READY,
            )
        ],
        status=TaskPlanStatus.COMPLETED,
    )

    TaskPlanManager.activate_plan(plan=plan)

    assert plan.status == TaskPlanStatus.ACTIVE


def test_activate_plan_leaves_finished_plan_untouched():
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

    TaskPlanManager.activate_plan(plan=plan)

    assert plan.status == TaskPlanStatus.COMPLETED


def test_format_task_plan_renders_contract_and_evidence():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Document the runtime routing",
                status=TaskItemStatus.COMPLETED,
                success_criteria=[
                    "The routing table has file references"
                ],
                confirmed=True,
                evidence=[
                    "artifact: routing table export"
                ],
            )
        ],
    )

    text = format_task_plan(plan)

    assert "[completed] Document the runtime routing" in text
    assert "id: a1" in text
    assert "success criteria:" in text
    assert "The routing table has file references" in text
    assert "confirmed by critic: yes" in text
    assert "evidence:" in text
    assert "artifact: routing table export" in text


def test_format_task_plan_marks_unconfirmed_tasks():
    plan = build_plan(
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Document the runtime routing",
                status=TaskItemStatus.COMPLETED,
                success_criteria=[
                    "The routing table has file references"
                ],
            )
        ],
    )

    text = format_task_plan(plan)

    assert "confirmed by critic: no" in text
