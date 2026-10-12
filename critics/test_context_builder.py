"""Coverage for the PLAN_EXHAUSTED critic context branch."""

from critics.context_builder import build_critic_context
from models import ActiveTaskMemory, ExecutionMemory

from runtime.events import RuntimeEvent
from runtime.modes import RuntimeMode
from runtime.models import RuntimeState
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


def build_state(outcome) -> dict:
    return {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.REVIEWING,
            last_event=RuntimeEvent.PLAN_EXHAUSTED,
        ),
        "task_plan": TaskPlan(
            plan_id="plan-1",
            goal="explain the repository layout",
            status=TaskPlanStatus.COMPLETED,
            tasks=[
                TaskItem(
                    task_id="a1",
                    objective="Identify the core goal",
                    status=TaskItemStatus.COMPLETED,
                    success_criteria=[
                        "The core goal is named in the summary"
                    ],
                    confirmed=False,
                    evidence=[
                        "read_file: Verified the requirement."
                    ],
                )
            ],
        ),
        "plan_execution_outcome": outcome,
        "active_memory": ActiveTaskMemory(),
        "execution_memory": ExecutionMemory(),
        "artifact_references": [],
    }


def test_exhausted_review_without_outcome_keeps_cautions():
    context = build_critic_context(build_state(None))

    assert "PLAN_EXHAUSTED" in context.plan_execution_outcome
    assert "does NOT establish" in context.plan_execution_outcome
    assert "final semantic evaluation" in context.current_objective


def test_exhausted_review_shows_preserved_outcome_data():
    outcome = PlanExecutionOutcome(
        plan_id="plan-1",
        condition=PlanExecutionCondition.COMPLETED,
        completed_task_ids=["a1"],
    )

    context = build_critic_context(build_state(outcome))

    assert "Condition: completed" in context.plan_execution_outcome
    assert "- a1" in context.plan_execution_outcome
    assert "PLAN_EXHAUSTED: every task" not in (
        context.plan_execution_outcome
    )


def test_exhausted_review_task_plan_includes_contract_and_evidence():
    context = build_critic_context(build_state(None))

    assert "id: a1" in context.task_plan_summary
    assert "success criteria:" in context.task_plan_summary
    assert "confirmed by critic: no" in context.task_plan_summary
    assert (
        "read_file: Verified the requirement."
        in context.task_plan_summary
    )
