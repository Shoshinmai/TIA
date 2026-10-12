import pytest

from runtime.events import RuntimeEvent
from runtime.modes import RuntimeMode
from runtime.models import (
    RuntimeDecisionContext,
    RuntimeEvidence,
    RuntimeState,
)
from runtime.nodes import (
    INADMISSIBLE_DECISION_KEY,
    _apply_concurrent_critic_decision,
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


def build_state(
    *,
    inadmissible_count: int = 0,
) -> dict:
    plan = TaskPlan(
        plan_id="plan-1",
        goal="explain the repository layout",
        status=TaskPlanStatus.ACTIVE,
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

    runtime_state = RuntimeState(
        mode=RuntimeMode.REVIEWING,
        metadata={
            INADMISSIBLE_DECISION_KEY: inadmissible_count,
        },
    )

    outcome = PlanExecutionOutcome(
        plan_id="plan-1",
        condition=PlanExecutionCondition.PARTIALLY_COMPLETED,
        completed_task_ids=["a1"],
        failed_task_ids=["a2"],
    )

    return {
        "runtime_state": runtime_state,
        "task_plan": plan,
        "plan_execution_outcome": outcome,
        "execution_workflow": None,
    }


def goal_completion_context() -> RuntimeDecisionContext:
    return RuntimeDecisionContext(
        rationale="The user's goal has been achieved.",
        evidence=[
            RuntimeEvidence(
                source="execution",
                observation="The completed task answered the question.",
            )
        ],
        decision_scope="goal",
    )


def test_failed_task_blocks_goal_completion_and_triggers_retry(
    inadmissible_count: int = 0,
):
    state = build_state(inadmissible_count=inadmissible_count)

    result = _apply_concurrent_critic_decision(
        state=state,
        event=RuntimeEvent.GOAL_COMPLETED,
        decision_context=goal_completion_context(),
        runtime_state=state["runtime_state"],
    )

    runtime_state = result["runtime_state"]

    assert runtime_state.mode == RuntimeMode.EXECUTING
    assert result["plan_execution_outcome"] is None
    assert result["critic_rejection"]

    failed_task = next(
        task
        for task in result["task_plan"].tasks
        if task.task_id == "a2"
    )

    assert failed_task.status == TaskItemStatus.READY
    # Goal completion rejection follows normal recovery, not inadmissible path
    assert runtime_state.metadata.get(INADMISSIBLE_DECISION_KEY, 0) == inadmissible_count


def test_goal_completion_never_accepted_when_contradicts_state():
    """
    GOAL_COMPLETED is never accepted if it contradicts authoritative state.
    No rejection budget bypass exists.
    """
    state = build_state(inadmissible_count=0)

    result = _apply_concurrent_critic_decision(
        state=state,
        event=RuntimeEvent.GOAL_COMPLETED,
        decision_context=goal_completion_context(),
        runtime_state=state["runtime_state"],
    )

    runtime_state = result["runtime_state"]

    # Still rejected, still follows recovery
    assert result["critic_rejection"] is not None
    assert runtime_state.mode == RuntimeMode.EXECUTING


def test_completion_is_accepted_when_the_plan_is_proven_complete():
    plan = TaskPlan(
        plan_id="plan-1",
        goal="explain the repository layout",
        status=TaskPlanStatus.COMPLETED,
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Read the project README",
                status=TaskItemStatus.COMPLETED,
            )
        ],
    )

    runtime_state = RuntimeState(mode=RuntimeMode.REVIEWING)

    state = {
        "runtime_state": runtime_state,
        "task_plan": plan,
        "plan_execution_outcome": PlanExecutionOutcome(
            plan_id="plan-1",
            condition=PlanExecutionCondition.COMPLETED,
            completed_task_ids=["a1"],
        ),
        "execution_workflow": None,
    }

    result = _apply_concurrent_critic_decision(
        state=state,
        event=RuntimeEvent.GOAL_COMPLETED,
        decision_context=goal_completion_context(),
        runtime_state=runtime_state,
    )

    assert result["runtime_state"].mode == RuntimeMode.FINISHED
    assert result["critic_rejection"] is None