from __future__ import annotations

from observer.agentic_loop_observation_models import (
    ObservationRecord,
)
from output.models import AgentOutput, OutputType
from runtime.agentic_loop_critic_models import (
    CriticConsultationState,
)
from runtime.agentic_loop_models import (
    AgenticLoopAction,
    AgenticLoopResult,
    AgenticLoopStatus,
)
from runtime.agentic_loop_operations import (
    DEFAULT_AGENTIC_LOOP_CRITIC_MODEL,
    DEFAULT_AGENTIC_LOOP_MODEL,
    analyze_capability_result,
    consult_critic_once,
    decide_next_action,
    end_critic_consultation,
    execute_selected_capability,
    render_critic_feedback,
    repeated_action_observation,
    should_block_repeated_action,
)
from state import TerminalState
from tools import TOOLS


def _observations(state: TerminalState) -> list[ObservationRecord]:
    return list(state.get("agentic_loop_observations") or [])


def _recent_actions(state: TerminalState) -> list[str]:
    return list(state.get("agentic_loop_recent_actions") or [])


def _critic_state(state: TerminalState) -> CriticConsultationState:
    return state.get("agentic_loop_critic_state") or CriticConsultationState()


def _goal(state: TerminalState) -> str:
    task = state.get("task")
    goal = getattr(task, "goal", None)
    if not isinstance(goal, str) or not goal.strip():
        goal = state.get("goal")

    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Agentic-loop graph node requires the original task goal.")
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
            observations=[record.content for record in _observations(state)],
            error=(f"Agentic-loop decision failed: " f"{type(exc).__name__}: {exc}"),
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
    """Execute one capability and retain its source result for analysis."""

    decision = state.get("agentic_loop_decision")
    if decision is None or decision.action != AgenticLoopAction.CAPABILITY:
        return {}

    observations = _observations(state)
    next_sequence = max((record.sequence for record in observations), default=0) + 1

    if should_block_repeated_action(decision, observations):
        observation = repeated_action_observation(
            decision,
            sequence=next_sequence,
        )

        updated_observations = [
            *observations,
            observation,
        ]

        updated_actions = [
            *_recent_actions(state),
            f"CAPABILITY blocked as duplicate: {decision.capability_name}",
        ]

        return {
            "agentic_loop_observations": updated_observations,
            "agentic_loop_recent_actions": updated_actions,
            "agentic_loop_pending_tool_result": None,
            "agentic_loop_pending_tool_result_sequence": None,
        }

    step = await execute_selected_capability(
        decision,
        capabilities=TOOLS,
        sequence=next_sequence,
        goal=_goal(state),
        active_memory=state.get("active_memory"),
    )

    updated_actions = [
        *_recent_actions(state),
        step.action_summary,
    ]

    tool_results = list(state.get("agentic_loop_tool_results") or [])
    tool_results.append(step.tool_result)

    return {
        "agentic_loop_tool_results": tool_results,
        "agentic_loop_observations": [
            *observations,
            step.observation,
        ],
        "agentic_loop_recent_actions": updated_actions,
        "active_memory": step.active_memory,
        "agentic_loop_pending_tool_result": step.raw_result,
        "agentic_loop_pending_tool_result_sequence": step.tool_result.sequence,
    }


async def agentic_loop_tool_analyzer_node(
    state: TerminalState,
) -> dict:
    """Analyze a pending capability result using its registered analyzer.

    Specialized analysis is currently implemented only for search_files.
    Other registered families retain the explicit fallback observation.
    """

    pending_sequence = state.get("agentic_loop_pending_tool_result_sequence")

    if pending_sequence is None:
        # No capability result is pending. This includes duplicate-action
        # blocks, which already produced their own runtime observation.
        return {}

    tool_results = list(state.get("agentic_loop_tool_results") or [])

    tool_result = next(
        (
            record
            for record in reversed(tool_results)
            if record.sequence == pending_sequence
        ),
        None,
    )

    observations = _observations(state)

    # Locate the provisional observation created when this capability ran.
    # Its tool_result_sequence links it to the pending source result.
    provisional_index = next(
        (
            index
            for index, record in enumerate(observations)
            if record.tool_result_sequence == pending_sequence
        ),
        None,
    )

    if provisional_index is not None:
        observation_sequence = observations[provisional_index].sequence
    else:
        # Preserve a valid sequence if the provisional observation is missing.
        observation_sequence = (
            max(
                (record.sequence for record in observations),
                default=0,
            )
            + 1
        )

    observation = analyze_capability_result(
        tool_result,
        raw_result=state.get("agentic_loop_pending_tool_result"),
        fallback_sequence=observation_sequence,
    )

    updated_observations = list(observations)

    if provisional_index is not None:
        # Replace the raw provisional observation in place.
        updated_observations[provisional_index] = observation
    else:
        # Defensive fallback: preserve the analysis even if the provisional
        # observation was unexpectedly absent.
        updated_observations.append(observation)

    return {
        "agentic_loop_observations": updated_observations,
        "agentic_loop_pending_tool_result": None,
        "agentic_loop_pending_tool_result_sequence": None,
    }


async def agentic_loop_critic_node(state: TerminalState) -> dict:
    """Consult the critic when the main agent selects CONSULT_CRITIC."""

    decision = state.get("agentic_loop_decision")
    if decision is None or decision.action != AgenticLoopAction.CONSULT_CRITIC:
        return {}

    observations = _observations(state)
    critic_state = _critic_state(state)
    recent_actions = [
        *_recent_actions(state),
        f"CONSULT_CRITIC: {decision.critic_question or ''}",
    ]

    step = await consult_critic_once(
        decision,
        goal=_goal(state),
        observations=observations,
        recent_actions=recent_actions,
        consultation_active=state.get("agentic_loop_critic_active"),
        consultation_state=critic_state,
        # policy=CriticInvocationPolicy(),
        critic_model=DEFAULT_AGENTIC_LOOP_CRITIC_MODEL,
    )

    return {
        "agentic_loop_critic_state": step.state,
        "agentic_loop_critic_active": step.consultation_active,
        "agentic_loop_critic_responses_received": state.get(
            "agentic_loop_critic_responses_received", 0
        ),
        "agentic_loop_recent_actions": recent_actions,
    }


def end_agentic_loop_critic_consultation_node(
    state: TerminalState,
) -> dict:
    """Close a consultation when the main agent selects a non-critic action."""
    critic_state, active = end_critic_consultation(
        _critic_state(state),
        consultation_active=state.get("agentic_loop_critic_active", False),
    )
    return {
        "agentic_loop_critic_state": critic_state,
        "agentic_loop_critic_active": active,
    }


def agentic_loop_terminal_node(state: TerminalState) -> dict:
    """Persist an isolated-loop result and produce user-facing output.

    This path intentionally does not claim that the runtime's
    authoritative goal-completion gate has verified the goal.
    """
    result = state.get("agentic_loop_result")
    decision = state.get("agentic_loop_decision")
    observations = [record.content for record in _observations(state)]

    if result is None:
        decisions_made = state.get("agentic_loop_decisions_made", 0)
        critic_responses = state.get("agentic_loop_critic_responses_received", 0)

        if decision is None:
            result = AgenticLoopResult(
                status=AgenticLoopStatus.FAILED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses,
                observations=observations,
                error=(
                    "The isolated agentic loop reached its terminal "
                    "node without a decision or a result."
                ),
            )

        elif decision.action == AgenticLoopAction.FINISH:
            result = AgenticLoopResult(
                status=AgenticLoopStatus.FINISHED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses,
                final_response=decision.final_response,
                rationale=decision.rationale,
                completion_evidence=decision.completion_evidence,
                observations=observations,
            )

        elif decision.action == AgenticLoopAction.CLARIFICATION:
            result = AgenticLoopResult(
                status=AgenticLoopStatus.CLARIFICATION_REQUIRED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses,
                clarification_question=decision.clarification_question,
                rationale=decision.rationale,
                observations=observations,
            )

        elif decision.action == AgenticLoopAction.COMPLEX_EXECUTION:
            result = AgenticLoopResult(
                status=AgenticLoopStatus.COMPLEX_EXECUTION_REQUESTED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses,
                rationale=decision.rationale,
                observations=observations,
            )

        else:
            result = AgenticLoopResult(
                status=AgenticLoopStatus.FAILED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses,
                observations=observations,
                error=(
                    "The isolated agentic loop reached its terminal "
                    f"node with non-terminal action {decision.action!r}."
                ),
            )

    if result.status == AgenticLoopStatus.FINISHED:
        # FINISH is not authoritative goal-completion verification.
        output_type = OutputType.PARTIAL_COMPLETION
        message = (
            "The isolated agentic loop produced the following result. "
            "The existing runtime completion gate was not run, so goal "
            "completion has not been independently verified.\n\n"
            f"{result.final_response}"
        )

    elif result.status == AgenticLoopStatus.CLARIFICATION_REQUIRED:
        output_type = OutputType.BLOCKED
        message = (
            "The agentic loop needs clarification before it can continue:\n\n"
            f"{result.clarification_question}"
        )

    elif result.status == AgenticLoopStatus.COMPLEX_EXECUTION_REQUESTED:
        output_type = OutputType.BLOCKED
        message = (
            "The isolated agentic loop requested complex execution, but "
            "that workflow is intentionally disabled in this test phase.\n\n"
            f"Reason: {result.rationale or 'No reason was provided.'}"
        )

    elif result.status == AgenticLoopStatus.FAILED:
        output_type = OutputType.FAILED
        message = (
            "The isolated agentic loop failed.\n\n"
            f"{result.error or 'No error details are available.'}"
        )

    else:
        output_type = OutputType.FAILED
        message = (
            "The isolated agentic loop failed.\n\n"
            f"{result.error or 'No error details are available.'}"
        )

    return {
        "agentic_loop_result": result,
        "agent_output": AgentOutput(
            output_type=output_type,
            message=message,
        ),
    }
