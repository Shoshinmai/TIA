from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from llm.llmclient import call_nvidia
from memory import artifact_store
from observer.agentic_loop_observation_models import (
    ObservationRecord,
    ObservationSource,
    ResultCompleteness,
    ToolExecutionOutcome,
    ToolResultRecord,
    ToolResultStorageStatus,
)
from prompts.agentic_loop_critic_prompt import AGENTIC_LOOP_CRITIC_PROMPT
from prompts.agentic_loop_prompt import AGENTIC_LOOP_PROMPT
from runtime.agentic_loop_context import build_agentic_loop_context
from runtime.agentic_loop_critic_models import (
    CriticAdvice,
    CriticConsultationRequest,
    CriticConsultationState,
    CriticConsultationStatus,
    CriticDialogueContext,
    CriticDialogueTurn,
    DialogueSpeaker,
)
from runtime.agentic_loop_models import (
    AgenticLoopAction,
    AgenticLoopDecision,
)
from tool_analyzer.discovery import analyze_search_files_result, format_discovery_analysis
from tool_analyzer.registry import ToolAnalyzerFamily, resolve_tool_analyzer_family
from tools import TOOLS

DEFAULT_AGENTIC_LOOP_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
# DEFAULT_AGENTIC_LOOP_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_AGENTIC_LOOP_CRITIC_MODEL = DEFAULT_AGENTIC_LOOP_MODEL


@dataclass(frozen=True, slots=True)
class CapabilityStep:
    observation: ObservationRecord
    tool_result: ToolResultRecord
    action_summary: str
    active_memory: Any | None = None
    raw_result: Any = None


@dataclass(frozen=True, slots=True)
class CriticStep:
    state: CriticConsultationState
    feedback: str
    response_received: bool
    consultation_active: bool


def bound_observation(observation: Any) -> str:
    """Convert an observation to text for storage and prompt use."""
    rendered = (
        observation if isinstance(observation, str) else str(observation)
    ).strip()
    return rendered or "(empty observation)"


def _agentic_loop_capabilities(
    capabilities: Sequence[Any] | None,
) -> list[Any]:
    """Return the capabilities available to the isolated loop."""
    available = TOOLS if capabilities is None else capabilities
    return list(available)


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

def analyze_capability_result(
    tool_result: ToolResultRecord | None,
    *,
    raw_result: Any = None,
    fallback_sequence: int,
) -> ObservationRecord:
    """Create the bounded observation for a capability result.

    The original source result is preserved separately in the
    ToolResultRecord or ArtifactStore. This operation only creates
    the representation supplied to the agent.
    """
    source = ObservationSource.CAPABILITY
    source_name = "tool_analyzer"
    tool_result_sequence = fallback_sequence
    artifact_id = None
    action_signature = None

    if tool_result is None:
        content = (
            "Tool analysis was skipped because the corresponding "
            f"tool-result record for sequence {fallback_sequence} "
            "could not be found. No interpretation was produced."
        )
        source = ObservationSource.RUNTIME

    else:
        source_name = tool_result.tool_name
        tool_result_sequence = tool_result.sequence
        artifact_id = tool_result.artifact_id
        action_signature = tool_result.action_signature

        family = resolve_tool_analyzer_family(tool_result.tool_name)

        if tool_result.outcome == ToolExecutionOutcome.RAISED_EXCEPTION:
            content = (
                f"Capability: {tool_result.tool_name}\n"
                "Specialized analysis was skipped because capability "
                "execution raised an exception.\n"
                f"Execution error: {tool_result.error_message or 'Unavailable'}"
            )

        elif tool_result.outcome == ToolExecutionOutcome.NOT_ATTEMPTED:
            content = (
                f"Capability: {tool_result.tool_name}\n"
                "Specialized analysis was skipped because capability "
                "execution was not attempted."
            )

        elif family is None:
            content = (
                f"Capability: {tool_result.tool_name}\n"
                "No analyzer family is registered for this capability. "
                "Specialized analysis was skipped."
            )

        elif (
            family == ToolAnalyzerFamily.DISCOVERY
            and tool_result.tool_name == "search_files"
        ):
            source_result = raw_result
            if source_result is None:
                source_result = tool_result.raw_result

            try:
                analysis = analyze_search_files_result(
                    source_result,
                    source_artifact_id=artifact_id,
                )
                content = format_discovery_analysis(analysis)

            except Exception as exc:
                content = (
                    f"Capability: {tool_result.tool_name}\n"
                    "Discovery analysis failed. The original capability "
                    "result remains preserved separately.\n"
                    f"Analysis error: {type(exc).__name__}: {exc}"
                )

        else:
            content = (
                f"Capability: {tool_result.tool_name}\n"
                f"Registered analyzer family: {family.value}\n"
                "Specialized analysis is not implemented for this "
                "capability yet. The original result has not been "
                "interpreted by a specialized analyzer."
            )

        if artifact_id:
            content += (
                "\nOriginal result is available through its stored artifact."
                f"\nArtifact ID: {artifact_id}"
            )

        elif tool_result.storage_error:
            content += (
                "\nOriginal result storage failed. The source payload is "
                "retained in the in-memory tool-result record."
                f"\nStorage error: {tool_result.storage_error}"
            )

    return ObservationRecord(
        sequence=fallback_sequence,
        source=source,
        source_name=source_name,
        action_signature=action_signature,
        content=bound_observation(content),
        tool_result_sequence=tool_result_sequence,
        content_truncated=False,
        artifact_id=artifact_id,
    )

def format_critic_advice(advice: CriticAdvice) -> str:
    parts = [f"Advice: {advice.advice}"]

    if advice.uncertainty:
        parts.append(f"Uncertainty: {advice.uncertainty}")

    if advice.follow_up_question:
        parts.append(f"Follow-up question: {advice.follow_up_question}")

    return "\n".join(parts)


def render_critic_feedback(state: CriticConsultationState) -> str:
    """Render dialogue separately from factual observations."""
    sections: list[str] = []

    if state.dialogue_summary:
        sections.extend(["Earlier consultation summary:", state.dialogue_summary])

    if state.recent_exchange:
        sections.append("Most recent exchange:")
        for turn in state.recent_exchange:
            sections.append(f"{turn.speaker.value}: {turn.content}")

    return "\n".join(sections) or "No critic advice has been received."


def append_dialogue_summary(previous: str, exchange: str) -> str:
    """Append an exchange, preserving all text."""
    combined = "\n\n".join(
        part for part in (previous.strip(), exchange.strip()) if part
    )
    return combined


def bound_dialogue_turn(content: str) -> str:
    """Return a dialogue turn without arbitrary character truncation."""
    return content or "(empty dialogue turn)"


async def decide_next_action(
    state: Mapping[str, Any],
    *,
    observations: Sequence[str],
    capabilities: Sequence[Any] | None = None,
    goal: str | None = None,
    critic_feedback: str = "No critic consultation has been requested.",
    model: str = DEFAULT_AGENTIC_LOOP_MODEL,
) -> AgenticLoopDecision:
    """Build context and obtain exactly one structured decision."""
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
    result_was_returned = False
    raw_result: Any = None

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
            result_was_returned = True
            raw_result = result

            # Save the original payload before processing or truncating it.
            # Verify retrieval before publishing the artifact ID.
            try:
                artifact_id = artifact_store.save_tool_result(
                    tool_name=capability_name,
                    result=result,
                    sequence=sequence,
                    action_signature=action_signature,
                )
                stored_artifact = artifact_store.get(artifact_id)
                if stored_artifact is None:
                    raise RuntimeError(
                        "ArtifactStore.save_tool_result returned an ID "
                        "that could not be retrieved."
                    )

                tool_result = ToolResultRecord(
                    sequence=sequence,
                    tool_name=capability_name,
                    action_signature=action_signature,
                    outcome=ToolExecutionOutcome.RETURNED,
                    completeness=ResultCompleteness.UNKNOWN,
                    storage_status=ToolResultStorageStatus.STORED,
                    artifact_id=artifact_id,
                )

            except Exception as storage_exc:
                # Do not publish an artifact ID when saving or verification
                # fails. Keep the source payload as a fallback in graph state.
                tool_result = ToolResultRecord(
                    sequence=sequence,
                    tool_name=capability_name,
                    action_signature=action_signature,
                    outcome=ToolExecutionOutcome.RETURNED,
                    completeness=ResultCompleteness.UNKNOWN,
                    storage_status=ToolResultStorageStatus.FAILED,
                    storage_error=(f"{type(storage_exc).__name__}: {storage_exc}")[
                        :2_000
                    ],
                    raw_result=result,
                )

            content = format_capability_observation(
                capability_name=capability_name,
                result=result,
                goal=goal,
            )

            source = ObservationSource.CAPABILITY
            source_name = capability_name
            action_summary = f"CAPABILITY executed: {capability_name}"

        except Exception as exc:
            source = ObservationSource.CAPABILITY
            source_name = capability_name

            if result_was_returned:
                # Execution succeeded; downstream processing failed.
                content = (
                    f"Capability: {capability_name}\n"
                    "The capability returned a result, but processing "
                    f"that result failed: {type(exc).__name__}: {exc}"
                )
                action_summary = (
                    f"CAPABILITY returned; result processing failed: "
                    f"{capability_name}"
                )
            else:
                content = (
                    f"Capability: {capability_name}\n"
                    f"Execution error: {type(exc).__name__}: {exc}"
                )
                action_summary = f"CAPABILITY failed: {capability_name}"
                tool_result = ToolResultRecord(
                    sequence=sequence,
                    tool_name=capability_name or "unknown",
                    action_signature=action_signature,
                    outcome=ToolExecutionOutcome.RAISED_EXCEPTION,
                    completeness=ResultCompleteness.UNAVAILABLE,
                    error_message=f"{type(exc).__name__}: {exc}",
                )
    if tool_result.storage_status == ToolResultStorageStatus.STORED:
        content += (
            "\n\nOriginal capability result stored successfully."
            f"\nArtifact ID: {tool_result.artifact_id}"
            "\nUse read_artifact or search_artifact with this ID "
            "to retrieve the original result."
        )

    elif tool_result.storage_status == ToolResultStorageStatus.FAILED:
        content += (
            "\n\nWARNING: The original result could not be stored as "
            "a retrievable artifact. No artifact ID is available."
            "\nThe source payload is retained in the in-memory "
            "tool-result record for this run."
            f"\nStorage error: {tool_result.storage_error}"
        )

    observation = ObservationRecord(
        sequence=sequence,
        source=source,
        source_name=source_name,
        action_signature=action_signature,
        content=bound_observation(content),
        tool_result_sequence=sequence,
        content_truncated=False,
        artifact_id=(
            tool_result.artifact_id
            if tool_result.storage_status == ToolResultStorageStatus.STORED
            else None
        ),
    )

    return CapabilityStep(
        observation=observation,
        tool_result=tool_result,
        action_summary=action_summary,
        active_memory=active_memory,
        raw_result=raw_result,
    )


async def consult_critic_once(
    decision: AgenticLoopDecision,
    *,
    goal: str,
    observations: Sequence[ObservationRecord],
    recent_actions: Sequence[str],
    consultation_state: CriticConsultationState,
    # responses_this_run: int,
    consultation_active: bool,
    # policy: CriticInvocationPolicy,
    critic_model: str = DEFAULT_AGENTIC_LOOP_CRITIC_MODEL,
) -> CriticStep:
    """Perform at most one critic response attempt.

    The critic is advisory and is invoked only when the main agent
    explicitly requests it via CONSULT_CRITIC. No response budgets are
    enforced.
    """
    if decision.action != AgenticLoopAction.CONSULT_CRITIC:
        raise ValueError("consult_critic_once requires a CONSULT_CRITIC decision.")

    if not consultation_active:
        consultation_state = CriticConsultationState()
        consultation_active = True

    by_sequence = {record.sequence: record for record in observations}
    if decision.critic_observation_sequences:
        selected_observations = [
            by_sequence[sequence]
            for sequence in decision.critic_observation_sequences
            if sequence in by_sequence
        ]
    else:
        selected_observations = list(observations)

    request = CriticConsultationRequest(
        goal=goal,
        question=decision.critic_question or "",
        relevant_observations=selected_observations,
        recent_actions=list(recent_actions),
        proposed_approach=decision.critic_proposed_approach,
        dialogue_context=CriticDialogueContext(
            summary=consultation_state.dialogue_summary,
            recent_exchange=consultation_state.recent_exchange,
        ),
    )

    main_turn = CriticDialogueTurn(
        speaker=DialogueSpeaker.MAIN_AGENT,
        content=request.question,
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

    critic_advice_text = format_critic_advice(advice)
    critic_turn = CriticDialogueTurn(
        speaker=DialogueSpeaker.CRITIC,
        content=critic_advice_text,
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
