from __future__ import annotations

import asyncio
from typing import Any

import pytest

import runtime.agentic_loop_runner as runner_module
from runtime.agentic_loop_critic_models import CriticAdvice
from runtime.agentic_loop_critic_policy import CriticInvocationPolicy
from runtime.agentic_loop_models import (
    AgenticLoopAction,
    AgenticLoopDecision,
    AgenticLoopStatus,
)


def run_loop(*args, **kwargs):
    return asyncio.run(runner_module.run_agentic_loop(*args, **kwargs))


def make_decision(
    action: AgenticLoopAction,
    *,
    rationale: str = "This is the appropriate next action.",
    critic_question: str | None = None,
    critic_observation_sequences: list[int] | None = None,
    critic_proposed_approach: str | None = None,
    final_response: str | None = None,
) -> AgenticLoopDecision:
    return AgenticLoopDecision(
        action=action,
        rationale=rationale,
        critic_question=critic_question,
        critic_observation_sequences=critic_observation_sequences or [],
        critic_proposed_approach=critic_proposed_approach,
        final_response=final_response,
    )


@pytest.fixture
def state() -> dict[str, Any]:
    return {"goal": "Inspect the project and report the result."}


@pytest.fixture
def llm_queues(monkeypatch):
    decisions: list[AgenticLoopDecision] = []
    advice: list[CriticAdvice] = []
    calls: list[dict[str, Any]] = []

    async def fake_call_nvidia(**kwargs):
        calls.append(kwargs)
        state_model = kwargs["state_model"]

        if state_model is CriticAdvice:
            if not advice:
                raise AssertionError("Unexpected critic call.")
            return advice.pop(0)

        if state_model is AgenticLoopDecision:
            if not decisions:
                raise AssertionError("Unexpected main-agent call.")
            return decisions.pop(0)

        raise AssertionError(f"Unexpected state model: {state_model}")

    monkeypatch.setattr(runner_module, "call_nvidia", fake_call_nvidia)
    return decisions, advice, calls


def test_consultation_returns_control_to_main_agent(state, llm_queues):
    decisions, advice, calls = llm_queues

    decisions.extend([
        make_decision(
            AgenticLoopAction.CONSULT_CRITIC,
            critic_question="What should I inspect next?",
            critic_proposed_approach="Inspect the caller.",
        ),
        make_decision(
            AgenticLoopAction.FINISH,
            final_response="The inspection result was reported.",
        ),
    ])
    advice.append(
        CriticAdvice(
            advice="Inspect the caller to establish how the setting is used.",
            uncertainty="The supplied observations do not show the caller.",
        )
    )

    result = run_loop(state, capabilities=[])

    assert result.status == AgenticLoopStatus.FINISHED
    assert result.decisions_made == 2
    assert result.critic_responses_received == 1
    assert len(calls) == 3

    assert calls[0]["state_model"] is AgenticLoopDecision
    assert calls[1]["state_model"] is CriticAdvice
    assert calls[2]["state_model"] is AgenticLoopDecision

    assert "What should I inspect next?" in calls[1]["prompt"]
    assert "Inspect the caller." in calls[1]["prompt"]

    # Advice reaches the main agent through its separate feedback section.
    assert "Inspect the caller to establish how the setting is used." in (
        calls[2]["prompt"]
    )
    assert "Critic consultation history and advice" in calls[2]["prompt"]


def test_consultation_budget_blocks_an_extra_response(state, llm_queues):
    decisions, advice, calls = llm_queues

    decisions.extend([
        make_decision(
            AgenticLoopAction.CONSULT_CRITIC,
            critic_question="What should I inspect first?",
        ),
        make_decision(
            AgenticLoopAction.CONSULT_CRITIC,
            critic_question="Can you elaborate?",
        ),
        make_decision(
            AgenticLoopAction.FINISH,
            final_response="The result was reported after the advice limit.",
        ),
    ])
    advice.append(CriticAdvice(advice="Inspect the direct caller first."))

    policy = CriticInvocationPolicy(
        max_responses_per_consultation=1,
        max_responses_per_run=2,
    )

    result = run_loop(
        state,
        capabilities=[],
        critic_policy=policy,
    )

    assert result.status == AgenticLoopStatus.FINISHED
    assert result.decisions_made == 3
    assert result.critic_responses_received == 1

    critic_calls = [
        call for call in calls
        if call["state_model"] is CriticAdvice
    ]
    assert len(critic_calls) == 1

    main_calls = [
        call for call in calls
        if call["state_model"] is AgenticLoopDecision
    ]
    assert "response limit has been reached" in main_calls[2]["prompt"]


def test_critic_failure_does_not_fail_main_loop(state, llm_queues, monkeypatch):
    decisions, _, _ = llm_queues

    decisions.extend([
        make_decision(
            AgenticLoopAction.CONSULT_CRITIC,
            critic_question="Can you advise on the next step?",
        ),
        make_decision(
            AgenticLoopAction.FINISH,
            final_response="The main loop recovered from critic unavailability.",
        ),
    ])

    original_call = runner_module.call_nvidia

    async def failing_critic_call(**kwargs):
        if kwargs["state_model"] is CriticAdvice:
            raise RuntimeError("simulated critic outage")
        return await original_call(**kwargs)

    monkeypatch.setattr(
        runner_module,
        "call_nvidia",
        failing_critic_call,
    )

    result = run_loop(state, capabilities=[])

    assert result.status == AgenticLoopStatus.FINISHED
    assert result.decisions_made == 2
    assert result.critic_responses_received == 0


def test_selected_observation_sequences_are_sent_to_critic(
    state,
    llm_queues,
):
    decisions, advice, calls = llm_queues

    decisions.extend([
        make_decision(
            AgenticLoopAction.CONSULT_CRITIC,
            critic_question="What does the second observation imply?",
            critic_observation_sequences=[2],
        ),
        make_decision(
            AgenticLoopAction.FINISH,
            final_response="The analysis was completed.",
        ),
    ])
    advice.append(CriticAdvice(advice="Inspect the source of that result."))

    result = run_loop(
        state,
        observations=["First observation.", "Second observation."],
        capabilities=[],
    )

    assert result.status == AgenticLoopStatus.FINISHED
    critic_prompt = next(
        call["prompt"]
        for call in calls
        if call["state_model"] is CriticAdvice
    )

    assert "Second observation." in critic_prompt
    assert "First observation." not in critic_prompt


def test_invalid_critic_question_is_rejected():
    with pytest.raises(ValueError, match="critic_question"):
        AgenticLoopDecision(
            action=AgenticLoopAction.CONSULT_CRITIC,
            rationale="Advice might help.",
        )