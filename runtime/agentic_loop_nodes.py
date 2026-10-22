
from __future__ import annotations

from runtime.agentic_loop_context import MAX_OBSERVATION_COUNT
from runtime.agentic_loop_critic_models import (
    CriticConsultationState,
    ObservationRecord,
)
from runtime.agentic_loop_critic_policy import CriticInvocationPolicy
from runtime.agentic_loop_models import (
    AgenticLoopAction,
    AgenticLoopResult,
    AgenticLoopStatus,
)
from runtime.agentic_loop_operations import (
    DEFAULT_AGENTIC_LOOP_CRITIC_MODEL,
    DEFAULT_AGENTIC_LOOP_MODEL,
    bound_observation,
    consult_critic_once,
    decide_next_action,
    end_critic_consultation,
    execute_selected_capability,
    render_critic_feedback,
)
from state import TerminalState
from tools import TOOLS


def _observations(state: TerminalState) -> list[ObservationRecord]:
    return list(state.get("agentic_loop_observations") or [])[
        -MAX_OBSERVATION_COUNT:
    ]


def _recent_actions(state: TerminalState) -> list[str]:
    return list(state.get("agentic_loop_recent_actions") or [])[-5:]


def _critic_state(state: TerminalState) -> CriticConsultationState:
    return (
        state.get("agentic_loop_critic_state")
        or CriticConsultationState()
    )


def _goal(state: TerminalState) -> str:
    task = state.get("task")
    goal = getattr(task, "goal", None)
    if not isinstance(goal, str) or not goal.strip():
        goal = state.get("goal")

    if not isinstance(goal, str) or not goal.strip():
        raise ValueError(
            "Agentic-loop graph node requires the original task goal."
        )
    return goal.strip()


async def agentic_loop_decision_node(state: TerminalState) -> dict:
    """Choose exactly one action and persist the decision."""
    try:
        decision = await decide_next_action(
            state,
            observations=[record.content for record in _observations(state)],
            capabilities=TOOLS,
            goal=_goal(state),
            critic_feedback=render_critic_feedback(_critic_state(state)),
            model=DEFAULT_AGENTIC_LOOP_MODEL,
        )
    except Exception as exc:
        result = AgenticLoopResult(
            status=AgenticLoopStatus.FAILED,
            decisions_made=state.get("agentic_loop_decisions_made", 0),
            critic_responses_received=state.get(
                "agentic_loop_critic_responses_received", 0
            ),
            observations=[
                record.content for record in _observations(state)
            ],
            error=(
                f"Agentic-loop decision failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        )
        return {"agentic_loop_result": result}

    return {
        "agentic_loop_decision": decision,
        "agentic_loop_decisions_made": (
            state.get("agentic_loop_decisions_made", 0) + 1
        ),
        "agentic_loop_result": None,
    }


async def agentic_loop_capability_node(state: TerminalState) -> dict:
    """Execute the selected capability once and persist its observation."""
    decision = state.get("agentic_loop_decision")
    if decision is None or decision.action != AgenticLoopAction.CAPABILITY:
        return {}

    observations = _observations(state)
    next_sequence = max(
        (record.sequence for record in observations),
        default=0,
    ) + 1

    step = await execute_selected_capability(
        decision,
        capabilities=TOOLS,
        sequence=next_sequence,
    )

    updated_observations = [*observations, step.observation][
        -MAX_OBSERVATION_COUNT:
    ]
    updated_actions = [
        *_recent_actions(state),
        step.action_summary,
    ][-5:]

    return {
        "agentic_loop_observations": updated_observations,
        "agentic_loop_recent_actions": updated_actions,
    }


async def agentic_loop_critic_node(state: TerminalState) -> dict:
    """Consult the critic at most once for the current decision."""
    decision = state.get("agentic_loop_decision")
    if decision is None or decision.action != AgenticLoopAction.CONSULT_CRITIC:
        return {}

    observations = _observations(state)
    critic_state = _critic_state(state)
    recent_actions = [
        *_recent_actions(state),
        f"CONSULT_CRITIC: {decision.critic_question or ''}",
    ][-5:]

    step = await consult_critic_once(
        decision,
        goal=_goal(state),
        observations=observations,
        recent_actions=recent_actions,
        consultation_state=critic_state,
        responses_this_run=state.get(
            "agentic_loop_critic_responses_received", 0
        ),
        consultation_active=state.get(
            "agentic_loop_critic_active", False
        ),
        policy=CriticInvocationPolicy(),
        critic_model=DEFAULT_AGENTIC_LOOP_CRITIC_MODEL,
    )

    response_count = state.get(
        "agentic_loop_critic_responses_received", 0
    )
    if step.response_received:
        response_count += 1

    return {
        "agentic_loop_critic_state": step.state,
        "agentic_loop_critic_active": step.consultation_active,
        "agentic_loop_critic_responses_received": response_count,
        "agentic_loop_recent_actions": recent_actions,
    }


def end_agentic_loop_critic_consultation_node(
    state: TerminalState,
) -> dict:
    """Close a consultation when the main agent selects a non-critic action."""
    critic_state, active = end_critic_consultation(
        _critic_state(state),
        consultation_active=state.get(
            "agentic_loop_critic_active", False
        ),
    )
    return {
        "agentic_loop_critic_state": critic_state,
        "agentic_loop_critic_active": active,
    }
