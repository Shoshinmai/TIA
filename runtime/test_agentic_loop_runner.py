
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

import runtime.agentic_loop_runner as runner_module
from runtime.agentic_loop_models import (
    AgenticLoopAction,
    AgenticLoopDecision,
    AgenticLoopStatus,
)


@dataclass
class FakeCapability:
    """Minimal stand-in for a registered LangChain capability."""

    name: str
    result: Any = None
    error: Exception | None = None
    calls: list[dict[str, Any]] | None = None

    async def ainvoke(self, arguments: dict[str, Any]) -> Any:
        if self.calls is None:
            self.calls = []

        self.calls.append(arguments)

        if self.error is not None:
            raise self.error

        return self.result


def make_decision(
    action: AgenticLoopAction,
    *,
    rationale: str = "This is the appropriate next action.",
    capability_name: str | None = None,
    arguments: dict[str, Any] | None = None,
    final_response: str | None = None,
    clarification_question: str | None = None,
    completion_evidence: list[str] | None = None,
) -> AgenticLoopDecision:
    """Construct a valid structured decision for a test."""

    return AgenticLoopDecision(
        action=action,
        rationale=rationale,
        capability_name=capability_name,
        arguments=arguments or {},
        final_response=final_response,
        clarification_question=clarification_question,
        completion_evidence=completion_evidence or [],
    )


def run_loop(*args, **kwargs):
    """Run the async agentic loop without requiring pytest-asyncio."""

    return asyncio.run(runner_module.run_agentic_loop(*args, **kwargs))


@pytest.fixture
def state() -> dict[str, Any]:
    return {"goal": "Inspect the project and report the result."}


@pytest.fixture
def decision_queue(monkeypatch):
    """Mock the LLM client with a sequence of structured decisions."""

    calls: list[dict[str, Any]] = []
    decisions: list[AgenticLoopDecision] = []

    async def fake_call_nvidia(**kwargs):
        calls.append(kwargs)

        if not decisions:
            raise AssertionError(
                "The runner requested more LLM decisions than expected."
            )

        return decisions.pop(0)

    monkeypatch.setattr(
        runner_module,
        "call_nvidia",
        fake_call_nvidia,
    )

    return decisions, calls


def test_finish_returns_final_response_and_evidence(
    state,
    decision_queue,
):
    decisions, calls = decision_queue
    decisions.append(
        make_decision(
            AgenticLoopAction.FINISH,
            rationale="The requested inspection is complete.",
            final_response="The project was inspected.",
            completion_evidence=["The inspection result was returned."],
        )
    )

    result = run_loop(
        state,
        capabilities=[],
    )

    assert result.status == AgenticLoopStatus.FINISHED
    assert result.decisions_made == 1
    assert result.final_response == "The project was inspected."
    assert result.completion_evidence == [
        "The inspection result was returned."
    ]
    assert len(calls) == 1
    assert calls[0]["subagent"] is True
    assert calls[0]["state_model"] is runner_module.AgenticLoopDecision


def test_clarification_stops_and_returns_question(
    state,
    decision_queue,
):
    decisions, _ = decision_queue
    decisions.append(
        make_decision(
            AgenticLoopAction.CLARIFICATION,
            rationale="The target directory is ambiguous.",
            clarification_question="Which directory should I inspect?",
        )
    )

    result = run_loop(
        state,
        capabilities=[],
    )

    assert result.status == AgenticLoopStatus.CLARIFICATION_REQUIRED
    assert result.decisions_made == 1
    assert (
        result.clarification_question
        == "Which directory should I inspect?"
    )


def test_complex_execution_requests_handoff_without_executing_it(
    state,
    decision_queue,
):
    decisions, _ = decision_queue
    decisions.append(
        make_decision(
            AgenticLoopAction.COMPLEX_EXECUTION,
            rationale="The remaining work requires coordinated execution.",
        )
    )

    capability = FakeCapability(name="inspect_path")

    result = run_loop(
        state,
        capabilities=[capability],
    )

    assert (
        result.status
        == AgenticLoopStatus.COMPLEX_EXECUTION_REQUESTED
    )
    assert result.decisions_made == 1
    assert result.rationale == (
        "The remaining work requires coordinated execution."
    )
    assert capability.calls is None


def test_capability_executes_with_arguments_and_loop_continues(
    state,
    decision_queue,
):
    decisions, calls = decision_queue
    decisions.extend(
        [
            make_decision(
                AgenticLoopAction.CAPABILITY,
                capability_name="inspect_path",
                arguments={"path": "src/main.py"},
            ),
            make_decision(
                AgenticLoopAction.FINISH,
                final_response="Inspection completed.",
                completion_evidence=["The capability returned file metadata."],
            ),
        ]
    )

    capability = FakeCapability(
        name="inspect_path",
        result={"exists": True, "type": "file"},
    )

    result = run_loop(
        state,
        capabilities=[capability],
    )

    assert result.status == AgenticLoopStatus.FINISHED
    assert result.decisions_made == 2
    assert capability.calls == [{"path": "src/main.py"}]
    assert len(calls) == 2
    assert "inspect_path" in calls[0]["prompt"]
    assert "exists" in result.observations[-1]
    assert "true" in result.observations[-1]


def test_capability_exception_becomes_observation_and_loop_recovers(
    state,
    decision_queue,
):
    decisions, calls = decision_queue
    decisions.extend(
        [
            make_decision(
                AgenticLoopAction.CAPABILITY,
                capability_name="flaky_tool",
                arguments={"query": "example"},
            ),
            make_decision(
                AgenticLoopAction.FINISH,
                rationale="The failure was observed and reported.",
                final_response="The capability failed; no result was obtained.",
            ),
        ]
    )

    capability = FakeCapability(
        name="flaky_tool",
        error=RuntimeError("simulated capability failure"),
    )

    result = run_loop(
        state,
        capabilities=[capability],
    )

    assert result.status == AgenticLoopStatus.FINISHED
    assert result.decisions_made == 2
    assert "Execution error: RuntimeError" in result.observations[-1]
    assert "simulated capability failure" in result.observations[-1]

    # The next LLM decision must receive the observed failure.
    assert "simulated capability failure" in calls[1]["prompt"]


def test_unknown_capability_is_observed_without_invocation(
    state,
    decision_queue,
):
    decisions, calls = decision_queue
    decisions.extend(
        [
            make_decision(
                AgenticLoopAction.CAPABILITY,
                capability_name="not_registered",
                arguments={"path": "somewhere"},
            ),
            make_decision(
                AgenticLoopAction.FINISH,
                final_response="The unavailable capability was not executed.",
            ),
        ]
    )

    registered = FakeCapability(name="inspect_path")

    result = run_loop(
        state,
        capabilities=[registered],
    )

    assert result.status == AgenticLoopStatus.FINISHED
    assert result.decisions_made == 2
    assert registered.calls is None
    assert "not_registered" in result.observations[-1]
    assert "not_registered" in calls[1]["prompt"]


def test_decision_budget_exhaustion_returns_bounded_status(
    state,
    decision_queue,
):
    decisions, calls = decision_queue
    decisions.extend(
        [
            make_decision(
                AgenticLoopAction.CAPABILITY,
                capability_name="missing_tool",
            ),
            make_decision(
                AgenticLoopAction.CAPABILITY,
                capability_name="missing_tool",
            ),
        ]
    )

    result = run_loop(
        state,
        capabilities=[],
        max_decisions=2,
    )

    assert result.status == AgenticLoopStatus.BUDGET_EXHAUSTED
    assert result.decisions_made == 2
    assert len(calls) == 2
    assert "decision budget" in result.rationale.lower()


def test_llm_error_returns_failed_result(state, monkeypatch):
    async def failing_call_nvidia(**kwargs):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(
        runner_module,
        "call_nvidia",
        failing_call_nvidia,
    )

    result = run_loop(
        state,
        capabilities=[],
    )

    assert result.status == AgenticLoopStatus.FAILED
    assert result.decisions_made == 0
    assert "RuntimeError" in result.error
    assert "simulated LLM outage" in result.error


def test_context_error_returns_failed_result(monkeypatch):
    async def unexpected_call_nvidia(**kwargs):
        pytest.fail("LLM should not be called if context construction fails.")

    monkeypatch.setattr(
        runner_module,
        "call_nvidia",
        unexpected_call_nvidia,
    )

    result = run_loop(
        {},
        capabilities=[],
    )

    assert result.status == AgenticLoopStatus.FAILED
    assert result.decisions_made == 0
    assert "original task goal" in result.error


@pytest.mark.parametrize("max_decisions", [0, -1, 51])
def test_invalid_decision_budget_raises_value_error(
    state,
    max_decisions,
):
    with pytest.raises(ValueError, match="max_decisions"):
        run_loop(
            state,
            capabilities=[],
            max_decisions=max_decisions,
        )
