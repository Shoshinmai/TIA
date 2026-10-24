from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from runtime.agentic_loop_context import MAX_OBSERVATION_COUNT
from runtime.agentic_loop_critic_models import (
    CriticConsultationState,
    ObservationRecord,
    ObservationSource,
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
    repeated_action_observation,
    should_block_repeated_action,
)
from tools import TOOLS


DEFAULT_MAX_DECISIONS = 10
MAX_ALLOWED_DECISIONS = 50


async def run_agentic_loop(
    state: Mapping[str, Any],
    *,
    goal: str | None = None,
    observations: Sequence[str] | None = None,
    capabilities: Sequence[Any] | None = None,
    model: str = DEFAULT_AGENTIC_LOOP_MODEL,
    critic_model: str | None = None,
    max_decisions: int = DEFAULT_MAX_DECISIONS,
    critic_policy: CriticInvocationPolicy | None = None,
) -> AgenticLoopResult:
    """Run the standalone loop using the shared single-step operations."""
    if not 1 <= max_decisions <= MAX_ALLOWED_DECISIONS:
        raise ValueError(
            f"max_decisions must be between 1 and "
            f"{MAX_ALLOWED_DECISIONS}; received {max_decisions}."
        )

    available_capabilities = list(TOOLS if capabilities is None else capabilities)
    policy = critic_policy or CriticInvocationPolicy()
    resolved_critic_model = critic_model or model

    seeded = [bound_observation(observation) for observation in (observations or ())]
    observation_records = [
        ObservationRecord(
            sequence=index,
            source=ObservationSource.OTHER,
            source_name="seeded_observation",
            content=content,
        )
        for index, content in enumerate(seeded, start=1)
    ][-MAX_OBSERVATION_COUNT:]

    next_sequence = len(seeded) + 1
    recent_actions: list[str] = []
    decisions_made = 0
    critic_responses_received = 0
    consultation_active = False
    consultation_state = CriticConsultationState()
    critic_feedback = "No critic consultation has been requested."

    def current_observations() -> list[str]:
        return [record.content for record in observation_records]

    def append_observation(record: ObservationRecord) -> None:
        observation_records.append(record)
        del observation_records[:-MAX_OBSERVATION_COUNT]

    def remember_action(action: str) -> None:
        recent_actions.append(action[:2_000])
        del recent_actions[:-5]

    for _ in range(max_decisions):
        try:
            decision = await decide_next_action(
                state,
                observations=current_observations(),
                capabilities=available_capabilities,
                goal=goal,
                critic_feedback=critic_feedback,
                model=model,
            )
        except Exception as exc:
            return AgenticLoopResult(
                status=AgenticLoopStatus.FAILED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses_received,
                observations=current_observations(),
                error=(
                    f"Agentic-loop decision failed: " f"{type(exc).__name__}: {exc}"
                ),
            )

        decisions_made += 1

        if decision.action == AgenticLoopAction.CONSULT_CRITIC:
            remember_action(f"CONSULT_CRITIC: {decision.critic_question or ''}")
            try:
                step = await consult_critic_once(
                    decision,
                    goal=goal or _resolve_goal(state),
                    observations=observation_records,
                    recent_actions=recent_actions,
                    consultation_state=consultation_state,
                    responses_this_run=critic_responses_received,
                    consultation_active=consultation_active,
                    policy=policy,
                    critic_model=resolved_critic_model,
                )
            except Exception as exc:
                return AgenticLoopResult(
                    status=AgenticLoopStatus.FAILED,
                    decisions_made=decisions_made,
                    critic_responses_received=critic_responses_received,
                    observations=current_observations(),
                    error=(
                        f"Agentic-loop critic operation failed: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )

            consultation_state = step.state
            consultation_active = step.consultation_active
            critic_feedback = step.feedback
            if step.response_received:
                critic_responses_received += 1
            continue

        consultation_state, consultation_active = end_critic_consultation(
            consultation_state,
            consultation_active=consultation_active,
        )

        if decision.action == AgenticLoopAction.FINISH:
            return AgenticLoopResult(
                status=AgenticLoopStatus.FINISHED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses_received,
                final_response=decision.final_response,
                rationale=decision.rationale,
                completion_evidence=decision.completion_evidence,
                observations=current_observations(),
            )

        if decision.action == AgenticLoopAction.CLARIFICATION:
            return AgenticLoopResult(
                status=AgenticLoopStatus.CLARIFICATION_REQUIRED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses_received,
                clarification_question=decision.clarification_question,
                rationale=decision.rationale,
                observations=current_observations(),
            )

        if decision.action == AgenticLoopAction.COMPLEX_EXECUTION:
            return AgenticLoopResult(
                status=AgenticLoopStatus.COMPLEX_EXECUTION_REQUESTED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses_received,
                rationale=decision.rationale,
                observations=current_observations(),
            )

        if decision.action == AgenticLoopAction.CAPABILITY:
            if should_block_repeated_action(decision, observation_records):
                append_observation(
                    repeated_action_observation(
                        decision,
                        sequence=next_sequence,
                    )
                )
                next_sequence += 1
                remember_action(
                    f"CAPABILITY blocked as duplicate: {decision.capability_name}"
                )
                continue
            step = await execute_selected_capability(
                decision,
                capabilities=available_capabilities,
                sequence=next_sequence,
            )
            next_sequence += 1
            append_observation(step.observation)
            remember_action(step.action_summary)
            continue

        return AgenticLoopResult(
            status=AgenticLoopStatus.FAILED,
            decisions_made=decisions_made,
            critic_responses_received=critic_responses_received,
            observations=current_observations(),
            error=f"Unsupported agentic-loop action: {decision.action!r}.",
        )

    return AgenticLoopResult(
        status=AgenticLoopStatus.BUDGET_EXHAUSTED,
        decisions_made=decisions_made,
        critic_responses_received=critic_responses_received,
        rationale=(
            "The agentic loop reached its decision budget before selecting "
            "FINISH, CLARIFICATION, or COMPLEX_EXECUTION."
        ),
        observations=current_observations(),
    )


def _resolve_goal(state: Mapping[str, Any]) -> str:
    task = state.get("task")
    task_goal = (
        task.get("goal") if isinstance(task, Mapping) else getattr(task, "goal", None)
    )
    if isinstance(task_goal, str) and task_goal.strip():
        return task_goal.strip()

    state_goal = state.get("goal")
    if isinstance(state_goal, str) and state_goal.strip():
        return state_goal.strip()

    raise ValueError("Cannot build AgenticLoopContext without an original task goal.")
