from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from llm.llmclient import call_nvidia
from observer.agentic_loop_observation_models import (
    MAX_OBSERVATION_CHARS,
    ObservationRecord,
    ObservationSource,
    ResultCompleteness,
    ToolExecutionOutcome,
    ToolResultRecord,
)
from prompts.agentic_loop_critic_prompt import AGENTIC_LOOP_CRITIC_PROMPT
from prompts.agentic_loop_prompt import AGENTIC_LOOP_PROMPT
from result_processing.processor import process_tool_result
from result_processing.state_mutator import mutate_state
from runtime.agentic_loop_context import (
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
    MAX_DIALOGUE_SUMMARY_CHARS,
    MAX_DIALOGUE_TURN_CHARS,
)
from runtime.agentic_loop_critic_policy import CriticInvocationPolicy
from runtime.agentic_loop_models import (
    AgenticLoopAction,
    AgenticLoopDecision,
)
from tools import TOOLS
from utils.normalized_result_formatter import format_normalized_result


DEFAULT_AGENTIC_LOOP_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
# DEFAULT_AGENTIC_LOOP_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_AGENTIC_LOOP_CRITIC_MODEL = DEFAULT_AGENTIC_LOOP_MODEL

_OBSERVATION_TRUNCATION_MARKER = "\n...[observation truncated]"
_DIALOGUE_TRUNCATION_MARKER = "\n...[earlier dialogue truncated]"
_ARTIFACT_CAPABILITY_NAMES = frozenset(
    {
        "search_artifact",
        "read_artifact",
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityStep:
    observation: ObservationRecord
    tool_result: ToolResultRecord
    action_summary: str
    active_memory: Any | None = None


@dataclass(frozen=True, slots=True)
class CriticStep:
    state: CriticConsultationState
    feedback: str
    response_received: bool
    consultation_active: bool


def bound_observation(observation: Any) -> str:
    """Convert an observation to bounded text for storage and prompt use."""
    rendered = (
        observation if isinstance(observation, str) else str(observation)
    ).strip()

    from runtime.agentic_loop_context import MAX_OBSERVATION_CHARS

    if len(rendered) <= MAX_OBSERVATION_CHARS:
        return rendered or "(empty observation)"

    available = max(
        0,
        MAX_OBSERVATION_CHARS - len(_OBSERVATION_TRUNCATION_MARKER),
    )
    return rendered[:available] + _OBSERVATION_TRUNCATION_MARKER


def _agentic_loop_capabilities(
    capabilities: Sequence[Any] | None,
) -> list[Any]:
    """Return capabilities permitted in the artifact-free isolated loop."""
    available = TOOLS if capabilities is None else capabilities

    return [
        capability
        for capability in available
        if getattr(capability, "name", None) not in _ARTIFACT_CAPABILITY_NAMES
    ]


def format_capability_observation(
    *,
    capability_name: str,
    result: Any,
    goal: str | None = None,
) -> str:
    """Render a fallback observation when structured processing is unavailable."""
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

    return f"Capability: {capability_name}\n" f"Returned result:\n{rendered_result}"


def format_critic_advice(advice: CriticAdvice) -> str:
    parts = [f"Advice: {advice.advice}"]

    if advice.uncertainty:
        parts.append(f"Uncertainty: {advice.uncertainty}")

    if advice.follow_up_question:
        parts.append(f"Follow-up question: {advice.follow_up_question}")

    return "\n".join(parts)


def render_critic_feedback(state: CriticConsultationState) -> str:
    """Render bounded dialogue separately from factual observations."""
    sections: list[str] = []

    if state.dialogue_summary:
        sections.extend(["Earlier consultation summary:", state.dialogue_summary])

    if state.recent_exchange:
        sections.append("Most recent exchange:")
        for turn in state.recent_exchange:
            sections.append(f"{turn.speaker.value}: {turn.content}")

    return "\n".join(sections) or "No critic advice has been received."


def append_dialogue_summary(previous: str, exchange: str) -> str:
    """Append an exchange while keeping the summary within its contract."""
    combined = "\n\n".join(
        part for part in (previous.strip(), exchange.strip()) if part
    )

    if len(combined) <= MAX_DIALOGUE_SUMMARY_CHARS:
        return combined

    marker = _DIALOGUE_TRUNCATION_MARKER
    available = MAX_DIALOGUE_SUMMARY_CHARS - len(marker)
    return marker + combined[-available:]


def bound_dialogue_turn(content: str) -> str:
    """Bound one dialogue turn to the model's configured field limit."""
    if len(content) <= MAX_DIALOGUE_TURN_CHARS:
        return content or "(empty dialogue turn)"

    marker = "\n...[dialogue turn truncated]"
    available = max(0, MAX_DIALOGUE_TURN_CHARS - len(marker))
    return content[:available] + marker


async def decide_next_action(
    state: Mapping[str, Any],
    *,
    observations: Sequence[str],
    capabilities: Sequence[Any] | None = None,
    goal: str | None = None,
    critic_feedback: str = "No critic consultation has been requested.",
    model: str = DEFAULT_AGENTIC_LOOP_MODEL,
) -> AgenticLoopDecision:
    """Build bounded context and obtain exactly one structured decision."""
    available_capabilities = _agentic_loop_capabilities(capabilities)

    context = build_agentic_loop_context(
        state=state,
        observations=observations,
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

    return decision


async def execute_selected_capability(
    decision: AgenticLoopDecision,
    *,
    capabilities: Sequence[Any] | None = None,
    sequence: int,
    goal: str | None = None,
    active_memory: Any | None = None,
) -> CapabilityStep:
    """Execute one capability and return its factual observation.

    Unknown capabilities and execution exceptions become observations rather
    than escaping as exceptions. This matches the standalone runner contract.
    """
    if decision.action != AgenticLoopAction.CAPABILITY:
        raise ValueError("execute_selected_capability requires a CAPABILITY decision.")

    available_capabilities = _agentic_loop_capabilities(capabilities)
    capability_name = decision.capability_name or ""
    capability_map = {
        capability.name: capability
        for capability in available_capabilities
        if isinstance(getattr(capability, "name", None), str)
        and capability.name.strip()
    }
    capability = capability_map.get(capability_name)
    action_signature = capability_action_signature(decision)
    tool_result: ToolResultRecord

    if capability is None:
        content = (
            "Capability execution was not attempted: "
            f"{capability_name!r} is not in the registered "
            "capability set for this invocation."
        )
        source = ObservationSource.RUNTIME
        source_name = "capability_dispatch"
        action_summary = f"CAPABILITY unavailable: {capability_name}"
        tool_result = ToolResultRecord(
            sequence=sequence,
            tool_name=capability_name or "unknown",
            action_signature=action_signature,
            outcome=ToolExecutionOutcome.NOT_ATTEMPTED,
            completeness=ResultCompleteness.UNAVAILABLE,
        )
    else:
        try:
            result = await capability.ainvoke(decision.arguments)
            tool_result = ToolResultRecord(
                sequence=sequence,
                tool_name=capability_name,
                action_signature=action_signature,
                outcome=ToolExecutionOutcome.RETURNED,
                completeness=ResultCompleteness.UNKNOWN,
                raw_result=result,
            )

            if (
                isinstance(result, dict)
                and active_memory is not None
                and isinstance(goal, str)
                and goal.strip()
            ):
                # process_tool_result reads goal and active_memory.
                # No artifact is saved here; the isolated path uses
                # artifact-free observation formatting.
                processing_state = {
                    "goal": goal.strip(),
                    "active_memory": active_memory,
                }

                processed = await process_tool_result(
                    state=processing_state,  # type: ignore[arg-type]
                    tool_name=capability_name,
                    raw_result=result,
                    include_artifacts=False,
                )

                # Reuse the existing deterministic quality controls.
                mutate_state(
                    state=processing_state,  # type: ignore[arg-type]
                    proposal=processed.memory_update,
                )

                content = (
                    f"Capability: {capability_name}\n"
                    f"Execution success: "
                    f"{processed.normalized_result.execution.success}\n"
                    f"Progress made: "
                    f"{processed.normalized_result.execution.progress_made}\n\n"
                    f"{processed.formatted_observation}"
                )
            else:
                # Preserve visibility into results that do not fit the
                # structured processor's input contract.
                content = format_capability_observation(
                    capability_name=capability_name,
                    result=result,
                    goal=goal,
                )

            source = ObservationSource.CAPABILITY
            source_name = capability_name
            action_summary = f"CAPABILITY executed: {capability_name}"
        except Exception as exc:
            content = (
                f"Capability: {capability_name}\n"
                f"Execution error: {type(exc).__name__}: {exc}"
            )
            source = ObservationSource.CAPABILITY
            source_name = capability_name
            action_summary = f"CAPABILITY failed: {capability_name}"
            tool_result = ToolResultRecord(
                sequence=sequence,
                tool_name=capability_name or "unknown",
                action_signature=action_signature,
                outcome=ToolExecutionOutcome.RAISED_EXCEPTION,
                completeness=ResultCompleteness.UNAVAILABLE,
                error_message=f"{type(exc).__name__}: {exc}"[:2_000],
            )

    observation_was_truncated = len(content.strip()) > MAX_OBSERVATION_CHARS

    observation = ObservationRecord(
        sequence=sequence,
        source=source,
        source_name=source_name[:200],
        action_signature=action_signature,
        content=bound_observation(content),
        tool_result_sequence=sequence,
        content_truncated=observation_was_truncated,
    )

    return CapabilityStep(
        observation=observation,
        tool_result=tool_result,
        action_summary=action_summary[:2_000],
        active_memory=active_memory,
    )


async def consult_critic_once(
    decision: AgenticLoopDecision,
    *,
    goal: str,
    observations: Sequence[ObservationRecord],
    recent_actions: Sequence[str],
    consultation_state: CriticConsultationState,
    responses_this_run: int,
    consultation_active: bool,
    policy: CriticInvocationPolicy,
    critic_model: str = DEFAULT_AGENTIC_LOOP_CRITIC_MODEL,
) -> CriticStep:
    """Perform at most one critic response attempt.

    A response-budget refusal is not a model call. A critic exception marks
    the critic unavailable but does not fail the main agent's loop.
    """
    if decision.action != AgenticLoopAction.CONSULT_CRITIC:
        raise ValueError("consult_critic_once requires a CONSULT_CRITIC decision.")

    if not consultation_active:
        consultation_state = CriticConsultationState()
        consultation_active = True

    exhausted_reason = policy.exhausted_reason(
        responses_this_consultation=consultation_state.responses_received,
        responses_this_run=responses_this_run,
    )

    if not policy.can_consult(
        main_agent_requested=True,
        responses_this_consultation=consultation_state.responses_received,
        responses_this_run=responses_this_run,
    ):
        if exhausted_reason == "consultation_limit":
            consultation_state.status = CriticConsultationStatus.TURN_LIMIT_REACHED
            feedback = (
                "The critic consultation response limit has been reached. "
                "No additional response was requested from the critic for "
                "this consultation. Continue using available evidence or "
                "take another action."
            )
        else:
            consultation_state.status = CriticConsultationStatus.RUN_BUDGET_EXHAUSTED
            feedback = (
                "The critic response budget for this run is exhausted. "
                "No additional critic response was requested. Continue using "
                "available evidence or take another action."
            )

        return CriticStep(
            state=consultation_state,
            feedback=feedback,
            response_received=False,
            consultation_active=consultation_active,
        )

    by_sequence = {record.sequence: record for record in observations}
    if decision.critic_observation_sequences:
        selected_observations = [
            by_sequence[sequence]
            for sequence in decision.critic_observation_sequences
            if sequence in by_sequence
        ]
    else:
        selected_observations = list(observations[-MAX_OBSERVATION_COUNT:])

    request = CriticConsultationRequest(
        goal=goal,
        question=decision.critic_question or "",
        relevant_observations=selected_observations,
        recent_actions=list(recent_actions[-5:]),
        proposed_approach=decision.critic_proposed_approach,
        dialogue_context=CriticDialogueContext(
            summary=consultation_state.dialogue_summary,
            recent_exchange=consultation_state.recent_exchange,
        ),
    )

    main_turn = CriticDialogueTurn(
        speaker=DialogueSpeaker.MAIN_AGENT,
        content=bound_dialogue_turn(request.question),
    )
    critic_prompt = AGENTIC_LOOP_CRITIC_PROMPT.format(
        consultation_request=json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    )

    try:
        advice = await call_nvidia(
            prompt=critic_prompt,
            model=critic_model,
            subagent=True,
            state_model=CriticAdvice,
        )
        if not isinstance(advice, CriticAdvice):
            raise TypeError(
                "The LLM client returned an unexpected critic response "
                f"type: {type(advice).__name__}."
            )
    except Exception as exc:
        consultation_state.status = CriticConsultationStatus.CRITIC_UNAVAILABLE
        return CriticStep(
            state=consultation_state,
            feedback=(
                "The requested critic consultation did not produce a "
                "usable response. No advice was received. Failure: "
                f"{type(exc).__name__}: {exc}. Do not infer advice from "
                "this failure; continue with available evidence or choose "
                "another action."
            ),
            response_received=False,
            consultation_active=consultation_active,
        )

    consultation_state.responses_received += 1
    consultation_state.status = CriticConsultationStatus.OPEN
    consultation_state.last_advice = advice

    critic_turn = CriticDialogueTurn(
        speaker=DialogueSpeaker.CRITIC,
        content=bound_dialogue_turn(format_critic_advice(advice)),
    )
    previous_exchange = "\n".join(
        f"{turn.speaker.value}: {turn.content}"
        for turn in consultation_state.recent_exchange
    )
    if previous_exchange:
        consultation_state.dialogue_summary = append_dialogue_summary(
            consultation_state.dialogue_summary,
            previous_exchange,
        )

    consultation_state.recent_exchange = [main_turn, critic_turn]

    return CriticStep(
        state=consultation_state,
        feedback=render_critic_feedback(consultation_state),
        response_received=True,
        consultation_active=consultation_active,
    )


def end_critic_consultation(
    state: CriticConsultationState,
    *,
    consultation_active: bool,
) -> tuple[CriticConsultationState, bool]:
    """End an active consultation when the main agent chooses another action."""
    if not consultation_active:
        return state, False

    if state.status in (
        CriticConsultationStatus.OPEN,
        CriticConsultationStatus.CRITIC_UNAVAILABLE,
    ):
        state.status = CriticConsultationStatus.ENDED_BY_MAIN_AGENT

    return state, False


def capability_action_signature(decision: AgenticLoopDecision) -> str:
    """Return a stable identity for a capability request."""
    payload = json.dumps(
        decision.arguments,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{decision.capability_name or ''}:{digest}"


def _previous_attempt_failed(observation: ObservationRecord) -> bool:
    """Recognize explicit failure evidence, not merely repeated activity."""
    text = observation.content.lower()
    failure_markers = (
        "execution error:",
        "success: false",
        '"success": false',
        "timed out",
        "timeout",
        "exception",
        "failed",
        "return code: 1",
    )
    return any(marker in text for marker in failure_markers)


def should_block_repeated_action(
    decision: AgenticLoopDecision,
    observations: Sequence[ObservationRecord],
) -> bool:
    """Block unexplained duplicate requests, allowing at most one justified retry."""
    if decision.action != AgenticLoopAction.CAPABILITY:
        return False

    signature = capability_action_signature(decision)
    matching = [
        record for record in observations if record.action_signature == signature
    ]

    if not matching:
        return False

    rationale = decision.rationale.lower()
    explicit_retry = any(
        marker in rationale
        for marker in (
            "retry",
            "retrying",
            "try again",
            "re-attempt",
            "reattempt",
        )
    )

    # Permit one explicitly justified retry only when the previous
    # execution produced concrete failure evidence. Any further repeat
    # is blocked, even if the rationale again says "retry".
    if len(matching) == 1 and explicit_retry and _previous_attempt_failed(matching[-1]):
        return False

    return True


def repeated_action_observation(
    decision: AgenticLoopDecision,
    *,
    sequence: int,
) -> ObservationRecord:
    """Build a runtime observation when an identical action is blocked."""
    signature = capability_action_signature(decision)
    return ObservationRecord(
        sequence=sequence,
        source=ObservationSource.RUNTIME,
        source_name="repeat_action_guard",
        action_signature=signature,
        content=bound_observation(
            "Repeated capability request was blocked without a justified "
            "retry. The same capability and arguments were already attempted. "
            "Use the existing evidence, choose a different action, or explain "
            "a retry only if the previous execution failed and another attempt "
            "is genuinely warranted."
        ),
    )
