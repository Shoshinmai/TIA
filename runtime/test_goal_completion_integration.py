"""Integration coverage for the GOAL_COMPLETED rejection loop.

The deterministic gate is unit-tested on its own. These tests drive the
Critic's own output through runtime routing and back into the Critic prompt,
so the reject -> correct -> requeue -> bounded acceptance cycle is exercised
as a whole without calling the network.
"""

import asyncio

from critics.integration import build_critic_runtime_event
from critics.models import (
    CriticDecision,
    CriticEvidence,
    CriticOutput,
)
from nodes import critics as critic_node_module
from runtime.events import RuntimeEvent
from runtime.goal_completion_gate import MAX_GOAL_COMPLETION_REJECTIONS
from runtime.modes import RuntimeMode
from runtime.models import RuntimeState
from runtime.nodes import (
    GOAL_COMPLETION_CONFLICT_KEY,
    GOAL_COMPLETION_REJECTION_COUNT_KEY,
    runtime_critic_result_node,
)
from task_plan.models import (
    TaskItem,
    TaskItemStatus,
    TaskPlan,
    TaskPlanStatus,
)


PLAN_STATUS_REASON = (
    "The TaskPlan status is 'active', not 'completed'."
)

REJECTION_REASONS = [
    (
        "The plan still contains objectives that did not reach a "
        "successful terminal state: a2 (failed): Persist the "
        "discovered knowledge."
    ),
    PLAN_STATUS_REASON,
]


def build_plan() -> TaskPlan:
    return TaskPlan(
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


def goal_completed_runtime_event():
    return build_critic_runtime_event(
        CriticOutput(
            decision=CriticDecision.GOAL_COMPLETED,
            rationale="The user's goal has been achieved.",
            evidence=[
                CriticEvidence(
                    source="execution",
                    observation="The completed task answered the question.",
                )
            ],
        )
    )


def build_state(rejection_count: int) -> dict:
    return {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.REVIEWING,
            metadata={
                GOAL_COMPLETION_REJECTION_COUNT_KEY: rejection_count,
            },
        ),
        "task_plan": build_plan(),
        "plan_execution_outcome": None,
        "execution_workflow": None,
        "critic_runtime_event": goal_completed_runtime_event(),
    }


def test_non_concurrent_completion_is_rejected_and_failed_task_is_requeued():
    state = build_state(rejection_count=0)

    result = runtime_critic_result_node(state)

    runtime_state = result["runtime_state"]

    assert result["critic_rejection"] == [PLAN_STATUS_REASON]
    assert result["plan_execution_outcome"] is None
    assert result["execution_workflow"] is None

    failed_task = next(
        task
        for task in result["task_plan"].tasks
        if task.task_id == "a2"
    )
    assert failed_task.status == TaskItemStatus.READY

    assert runtime_state.mode == RuntimeMode.EXECUTING
    assert (
        runtime_state.metadata[GOAL_COMPLETION_REJECTION_COUNT_KEY] == 1
    )
    assert GOAL_COMPLETION_CONFLICT_KEY not in runtime_state.metadata


def test_non_concurrent_completion_is_accepted_once_budget_is_exhausted():
    state = build_state(
        rejection_count=MAX_GOAL_COMPLETION_REJECTIONS,
    )

    result = runtime_critic_result_node(state)

    runtime_state = result["runtime_state"]

    assert result["critic_rejection"] is None
    assert runtime_state.mode == RuntimeMode.FINISHED
    assert runtime_state.metadata[GOAL_COMPLETION_CONFLICT_KEY]
    assert (
        runtime_state.metadata[GOAL_COMPLETION_REJECTION_COUNT_KEY]
        == MAX_GOAL_COMPLETION_REJECTIONS
    )


class _StubCriticContext:
    def __getattr__(self, name: str) -> str:
        return f"stub {name}"

    def model_dump(self) -> dict:
        return {}


def run_critic_with_fake_model(
    monkeypatch,
    decision: CriticDecision,
) -> tuple[dict, str]:
    """Run terminal_critic_node with the LLM replaced by a fixed decision."""

    captured: dict = {}

    async def fake_call_nvidia(
        prompt,
        model,
        subagent=False,
        state_model=None,
        tool=False,
    ):
        captured["prompt"] = prompt

        target_task_ids = ["a2"] if decision == CriticDecision.RETRY_TASK else []

        return CriticOutput(
            decision=decision,
            target_task_ids=target_task_ids,
            rationale="Runtime evidence supports this decision.",
            evidence=[
                CriticEvidence(
                    source="execution",
                    observation="The task outcome is known.",
                )
            ],
        )

    monkeypatch.setattr(critic_node_module, "call_nvidia", fake_call_nvidia)
    monkeypatch.setattr(
        critic_node_module,
        "build_critic_context",
        lambda state: _StubCriticContext(),
    )
    monkeypatch.setattr(
        critic_node_module,
        "TERMINAL_CRITIC_PROMPT",
        "CRITIC PROMPT",
    )

    state = {"critic_rejection": list(REJECTION_REASONS)}

    result = asyncio.run(
        critic_node_module.terminal_critic_node(state),
    )

    return result, captured["prompt"]


def test_rejection_reasons_reach_the_next_critic_prompt(
    monkeypatch,
):
    result, prompt = run_critic_with_fake_model(
        monkeypatch,
        CriticDecision.RETRY_TASK,
    )

    assert "GOAL COMPLETION CORRECTION" in prompt

    for reason in REJECTION_REASONS:
        assert reason in prompt

    # A recovery decision ends the correction cycle.
    assert result["critic_rejection"] is None


def test_rejection_survives_while_the_critic_keeps_claiming_completion(
    monkeypatch,
):
    result, prompt = run_critic_with_fake_model(
        monkeypatch,
        CriticDecision.GOAL_COMPLETED,
    )

    assert "GOAL COMPLETION CORRECTION" in prompt
    assert result["critic_rejection"] == REJECTION_REASONS
    assert result["critic_runtime_event"].event == RuntimeEvent.GOAL_COMPLETED


def task_completed_runtime_event(target_task_ids: list[str]):
    return build_critic_runtime_event(
        CriticOutput(
            decision=CriticDecision.TASK_COMPLETED,
            rationale=(
                "Execution evidence satisfies the task criteria."
            ),
            evidence=[
                CriticEvidence(
                    source="execution",
                    observation=(
                        "The completed workflow output matches "
                        "every success criterion."
                    ),
                )
            ],
            target_task_ids=target_task_ids,
        )
    )


def build_special_case_state(
    target_task_ids: list[str],
    *,
    second_task_confirmed: bool = False,
) -> dict:
    """A plan whose tasks are all completed, with no IN_PROGRESS
    task and no execution boundary: the PLAN_EXHAUSTED review."""

    tasks = [
        TaskItem(
            task_id="a1",
            objective="Identify the core goal",
            status=TaskItemStatus.COMPLETED,
            success_criteria=["The core goal is named in the summary"],
        ),
        TaskItem(
            task_id="a2",
            objective="Persist the discovered knowledge",
            status=TaskItemStatus.COMPLETED,
            success_criteria=["The knowledge is recorded in memory"],
            confirmed=second_task_confirmed,
        ),
    ]

    return {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.REVIEWING,
            metadata={
                GOAL_COMPLETION_REJECTION_COUNT_KEY: 0,
            },
        ),
        "task_plan": TaskPlan(
            plan_id="plan-1",
            goal="explain the repository layout",
            status=TaskPlanStatus.ACTIVE,
            tasks=tasks,
        ),
        "plan_execution_outcome": None,
        "execution_workflow": None,
        "critic_runtime_event": task_completed_runtime_event(
            target_task_ids,
        ),
    }


def test_task_completed_with_an_unconfirmed_leftover_stays_in_review():
    state = build_special_case_state(["a1"])

    result = runtime_critic_result_node(state)

    runtime_state = result["runtime_state"]

    assert runtime_state.mode == RuntimeMode.REVIEWING
    assert result["task_plan"].status == TaskPlanStatus.COMPLETED
    assert result["task_plan"].tasks[0].confirmed is True
    assert result["task_plan"].tasks[1].confirmed is False
    assert any(
        "a2" in reason and "never been confirmed" in reason
        for reason in result["critic_rejection"]
    )
    assert (
        runtime_state.metadata[GOAL_COMPLETION_REJECTION_COUNT_KEY] == 1
    )
    assert result["plan_execution_outcome"] is None


def test_goal_completion_is_admitted_once_every_target_is_confirmed():
    state = build_special_case_state(
        ["a1", "a2"],
        second_task_confirmed=False,
    )

    result = runtime_critic_result_node(state)

    runtime_state = result["runtime_state"]

    assert runtime_state.mode == RuntimeMode.FINISHED
    assert result["task_plan"].status == TaskPlanStatus.COMPLETED
    assert all(
        task.confirmed
        for task in result["task_plan"].tasks
    )
    assert result["critic_rejection"] is None
    assert GOAL_COMPLETION_CONFLICT_KEY not in runtime_state.metadata
