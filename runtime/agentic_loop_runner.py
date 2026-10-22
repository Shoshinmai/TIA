from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from llm.llmclient import call_nvidia
from prompts.agentic_loop_critic_prompt import AGENTIC_LOOP_CRITIC_PROMPT
from prompts.agentic_loop_prompt import AGENTIC_LOOP_PROMPT
from runtime.agentic_loop_context import (
    MAX_OBSERVATION_CHARS,
    MAX_OBSERVATION_COUNT,
    build_agentic_loop_context,
)
from runtime.agentic_loop_critic_models import (
    CriticAdvice,
    CriticConsultationRequest,
    CriticConsultationState,
    CriticConsultationStatus,
    CriticDialogueContext,
    CriticDialogueTurn,
    DialogueSpeaker,
    ObservationRecord,
    ObservationSource,
    MAX_DIALOGUE_SUMMARY_CHARS,
    MAX_DIALOGUE_TURN_CHARS,
)
from runtime.agentic_loop_critic_policy import CriticInvocationPolicy
from runtime.agentic_loop_models import (
    AgenticLoopAction,
    AgenticLoopDecision,
    AgenticLoopResult,
    AgenticLoopStatus,
)
from tools import TOOLS


DEFAULT_AGENTIC_LOOP_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_AGENTIC_LOOP_CRITIC_MODEL = DEFAULT_AGENTIC_LOOP_MODEL

DEFAULT_MAX_DECISIONS = 10
MAX_ALLOWED_DECISIONS = 50

_OBSERVATION_TRUNCATION_MARKER = "\n...[observation truncated]"
_DIALOGUE_TRUNCATION_MARKER = "\n...[earlier dialogue truncated]"


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
    """Run the standalone agentic loop with reactive critic consultation.

    The main agent selects each action. CONSULT_CRITIC obtains one structured
    advisory response, when permitted by the separate critic budgets, and
    then returns control to the main agent.

    This runner does not mutate state, invoke the complex-execution
    subsystem, or certify that a reported goal is complete.
    """
    if not 1 <= max_decisions <= MAX_ALLOWED_DECISIONS:
        raise ValueError(
            f"max_decisions must be between 1 and "
            f"{MAX_ALLOWED_DECISIONS}; received {max_decisions}."
        )

    available_capabilities = list(
        TOOLS if capabilities is None else capabilities
    )
    capability_map = {
        capability.name: capability
        for capability in available_capabilities
        if isinstance(getattr(capability, "name", None), str)
        and capability.name.strip()
    }

    policy = critic_policy or CriticInvocationPolicy()
    resolved_critic_model = critic_model or model

    seeded = [
        _bound_observation(observation)
        for observation in (observations or ())
    ]
    observation_records = [
        ObservationRecord(
            sequence=index,
            source=ObservationSource.OTHER,
            source_name="seeded_observation",
            content=content,
        )
        for index, content in enumerate(seeded, start=1)
    ][-MAX_OBSERVATION_COUNT:]

    next_observation_sequence = len(seeded) + 1
    recent_actions: list[str] = []

    decisions_made = 0
    critic_responses_received = 0
    consultation_active = False
    consultation_state = CriticConsultationState()
    critic_feedback = "No critic consultation has been requested."

    def append_observation(
        content: str,
        *,
        source: ObservationSource,
        source_name: str = "",
    ) -> None:
        nonlocal next_observation_sequence

        observation_records.append(
            ObservationRecord(
                sequence=next_observation_sequence,
                source=source,
                source_name=source_name[:200],
                content=_bound_observation(content),
            )
        )
        next_observation_sequence += 1

        del observation_records[:-MAX_OBSERVATION_COUNT]

    def current_observation_text() -> list[str]:
        return [record.content for record in observation_records]

    def remember_action(description: str) -> None:
        recent_actions.append(description[:2_000])
        del recent_actions[:-5]

    def end_consultation_if_active() -> None:
        nonlocal consultation_active

        if not consultation_active:
            return

        if consultation_state.status in (
            CriticConsultationStatus.OPEN,
            CriticConsultationStatus.CRITIC_UNAVAILABLE,
        ):
            consultation_state.status = (
                CriticConsultationStatus.ENDED_BY_MAIN_AGENT
            )

        consultation_active = False

    for _ in range(max_decisions):
        try:
            context = build_agentic_loop_context(
                state=state,
                observations=current_observation_text(),
                capabilities=available_capabilities,
                goal=goal,
            )

            prompt = AGENTIC_LOOP_PROMPT.format(
                **context.model_dump(),
                critic_feedback=critic_feedback,
            )

            decision = await call_nvidia(
                prompt=prompt,
                model=model,
                subagent=True,
                state_model=AgenticLoopDecision,
            )

            if not isinstance(decision, AgenticLoopDecision):
                raise TypeError(
                    "The LLM client returned an unexpected decision type: "
                    f"{type(decision).__name__}."
                )

            decisions_made += 1

        except Exception as exc:
            return AgenticLoopResult(
                status=AgenticLoopStatus.FAILED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses_received,
                observations=current_observation_text(),
                error=(
                    f"Agentic-loop decision failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        if decision.action == AgenticLoopAction.CONSULT_CRITIC:
            if not consultation_active:
                consultation_state = CriticConsultationState()
                consultation_active = True

            remember_action(
                f"CONSULT_CRITIC: {decision.critic_question or ''}"
            )

            exhausted_reason = policy.exhausted_reason(
                responses_this_consultation=(
                    consultation_state.responses_received
                ),
                responses_this_run=critic_responses_received,
            )

            if not policy.can_consult(
                main_agent_requested=True,
                responses_this_consultation=(
                    consultation_state.responses_received
                ),
                responses_this_run=critic_responses_received,
            ):
                if exhausted_reason == "consultation_limit":
                    consultation_state.status = (
                        CriticConsultationStatus.TURN_LIMIT_REACHED
                    )
                    critic_feedback = (
                        "The critic consultation response limit has been "
                        "reached. No additional response was requested from "
                        "the critic for this consultation. Continue using "
                        "available evidence or take another action."
                    )
                else:
                    consultation_state.status = (
                        CriticConsultationStatus.RUN_BUDGET_EXHAUSTED
                    )
                    critic_feedback = (
                        "The critic response budget for this run is "
                        "exhausted. No additional critic response was "
                        "requested. Continue using available evidence or "
                        "take another action."
                    )
                continue

            by_sequence = {
                record.sequence: record for record in observation_records
            }

            if decision.critic_observation_sequences:
                selected_observations = [
                    by_sequence[sequence]
                    for sequence in decision.critic_observation_sequences
                    if sequence in by_sequence
                ]
            else:
                selected_observations = observation_records[
                    -MAX_OBSERVATION_COUNT:
                ]

            consultation_request = CriticConsultationRequest(
                goal=context.goal,
                question=decision.critic_question or "",
                relevant_observations=selected_observations,
                recent_actions=recent_actions[-5:],
                proposed_approach=decision.critic_proposed_approach,
                dialogue_context=CriticDialogueContext(
                    summary=consultation_state.dialogue_summary,
                    recent_exchange=consultation_state.recent_exchange,
                ),
            )

            main_turn = CriticDialogueTurn(
                speaker=DialogueSpeaker.MAIN_AGENT,
                content=_bound_dialogue_turn(
                    consultation_request.question
                ),
            )

            critic_prompt = AGENTIC_LOOP_CRITIC_PROMPT.format(
                consultation_request=json.dumps(
                    consultation_request.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
            )

            try:
                advice = await call_nvidia(
                    prompt=critic_prompt,
                    model=resolved_critic_model,
                    subagent=True,
                    state_model=CriticAdvice,
                )

                if not isinstance(advice, CriticAdvice):
                    raise TypeError(
                        "The LLM client returned an unexpected critic "
                        f"response type: {type(advice).__name__}."
                    )

            except Exception as exc:
                consultation_state.status = (
                    CriticConsultationStatus.CRITIC_UNAVAILABLE
                )
                critic_feedback = (
                    "The requested critic consultation did not produce a "
                    "usable response. No advice was received. Failure: "
                    f"{type(exc).__name__}: {exc}. Do not infer advice from "
                    "this failure; continue with available evidence or "
                    "choose another action."
                )
                continue

            critic_responses_received += 1
            consultation_state.responses_received += 1
            consultation_state.status = CriticConsultationStatus.OPEN
            consultation_state.last_advice = advice

            critic_turn = CriticDialogueTurn(
                speaker=DialogueSpeaker.CRITIC,
                content=_bound_dialogue_turn(
                    _format_critic_advice(advice)
                ),
            )

            previous_exchange = "\n".join(
                f"{turn.speaker.value}: {turn.content}"
                for turn in consultation_state.recent_exchange
            )

            if previous_exchange:
                consultation_state.dialogue_summary = (
                    _append_dialogue_summary(
                        consultation_state.dialogue_summary,
                        previous_exchange,
                    )
                )

            consultation_state.recent_exchange = [
                main_turn,
                critic_turn,
            ]

            critic_feedback = _render_critic_feedback(
                consultation_state
            )

            # Critic advice remains separate from factual observations.
            continue

        # A non-consultation action ends the current consultation.
        end_consultation_if_active()

        if decision.action == AgenticLoopAction.FINISH:
            return AgenticLoopResult(
                status=AgenticLoopStatus.FINISHED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses_received,
                final_response=decision.final_response,
                rationale=decision.rationale,
                completion_evidence=decision.completion_evidence,
                observations=current_observation_text(),
            )

        if decision.action == AgenticLoopAction.CLARIFICATION:
            return AgenticLoopResult(
                status=AgenticLoopStatus.CLARIFICATION_REQUIRED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses_received,
                clarification_question=decision.clarification_question,
                rationale=decision.rationale,
                observations=current_observation_text(),
            )

        if decision.action == AgenticLoopAction.COMPLEX_EXECUTION:
            return AgenticLoopResult(
                status=AgenticLoopStatus.COMPLEX_EXECUTION_REQUESTED,
                decisions_made=decisions_made,
                critic_responses_received=critic_responses_received,
                rationale=decision.rationale,
                observations=current_observation_text(),
            )

        if decision.action == AgenticLoopAction.CAPABILITY:
            capability_name = decision.capability_name or ""
            capability = capability_map.get(capability_name)

            if capability is None:
                append_observation(
                    "Capability execution was not attempted: "
                    f"{capability_name!r} is not in the registered "
                    "capability set for this invocation.",
                    source=ObservationSource.RUNTIME,
                    source_name="capability_dispatch",
                )
                remember_action(
                    f"CAPABILITY unavailable: {capability_name}"
                )
                continue

            try:
                result = await capability.ainvoke(decision.arguments)
                append_observation(
                    _format_capability_observation(
                        capability_name=capability_name,
                        result=result,
                    ),
                    source=ObservationSource.CAPABILITY,
                    source_name=capability_name,
                )
                remember_action(f"CAPABILITY executed: {capability_name}")

            except Exception as exc:
                append_observation(
                    f"Capability: {capability_name}\n"
                    f"Execution error: {type(exc).__name__}: {exc}",
                    source=ObservationSource.CAPABILITY,
                    source_name=capability_name,
                )
                remember_action(f"CAPABILITY failed: {capability_name}")

            continue

        return AgenticLoopResult(
            status=AgenticLoopStatus.FAILED,
            decisions_made=decisions_made,
            critic_responses_received=critic_responses_received,
            observations=current_observation_text(),
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
        observations=current_observation_text(),
    )


def _format_capability_observation(
    *,
    capability_name: str,
    result: Any,
) -> str:
    """Format an actual capability result without semantic interpretation."""
    if isinstance(result, str):
        rendered_result = result
    else:
        try:
            rendered_result = json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except (TypeError, ValueError):
            rendered_result = str(result)

    return (
        f"Capability: {capability_name}\n"
        f"Returned result:\n{rendered_result}"
    )


def _format_critic_advice(advice: CriticAdvice) -> str:
    parts = [f"Advice: {advice.advice}"]

    if advice.uncertainty:
        parts.append(f"Uncertainty: {advice.uncertainty}")

    if advice.follow_up_question:
        parts.append(f"Follow-up question: {advice.follow_up_question}")

    return "\n".join(parts)


def _render_critic_feedback(
    state: CriticConsultationState,
) -> str:
    """Render bounded dialogue separately from factual observations."""
    sections: list[str] = []

    if state.dialogue_summary:
        sections.append("Earlier consultation summary:")
        sections.append(state.dialogue_summary)

    if state.recent_exchange:
        sections.append("Most recent exchange:")
        for turn in state.recent_exchange:
            sections.append(
                f"{turn.speaker.value}: {turn.content}"
            )

    return "\n".join(sections) or "No critic advice has been received."


def _append_dialogue_summary(previous: str, exchange: str) -> str:
    """Append an exchange while keeping the summary within its contract."""
    combined = "\n\n".join(
        part for part in (previous.strip(), exchange.strip()) if part
    )

    if len(combined) <= MAX_DIALOGUE_SUMMARY_CHARS:
        return combined

    marker = _DIALOGUE_TRUNCATION_MARKER
    available = MAX_DIALOGUE_SUMMARY_CHARS - len(marker)
    return marker + combined[-available:]


def _bound_dialogue_turn(content: str) -> str:
    """Bound one dialogue turn to the model's configured field limit."""
    if len(content) <= MAX_DIALOGUE_TURN_CHARS:
        return content or "(empty dialogue turn)"

    marker = "\n...[dialogue turn truncated]"
    available = max(0, MAX_DIALOGUE_TURN_CHARS - len(marker))
    return content[:available] + marker


def _bound_observation(observation: Any) -> str:
    """Convert an observation to bounded text for storage and prompt use."""
    rendered = (
        observation
        if isinstance(observation, str)
        else str(observation)
    ).strip()

    if len(rendered) <= MAX_OBSERVATION_CHARS:
        return rendered or "(empty observation)"

    available = max(
        0,
        MAX_OBSERVATION_CHARS - len(_OBSERVATION_TRUNCATION_MARKER),
    )
    return rendered[:available] + _OBSERVATION_TRUNCATION_MARKER