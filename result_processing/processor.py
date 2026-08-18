from agents.terminal.result_processing.memory_condenser import condense_memory
from agents.terminal.result_processing.models import RuntimeProcessingResult
from agents.terminal.state import TerminalState

from agents.terminal.result_processing.normalizer import (
    normalize_result,
)

from agents.terminal.result_processing.artifact_policy import (
    evaluate_artifact_candidate,
)

from agents.terminal.result_processing.state_mutator import (
    mutate_state,
)
from agents.terminal.utils.memory_formatter import format_active_memory
from agents.terminal.utils.normalized_result_formatter import format_normalized_result


def process_tool_result(
    *,
    state: TerminalState,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> RuntimeProcessingResult:
    """
    Process a raw tool result through the Runtime Processing Pipeline.

    This function is responsible for normalization, artifact
    policy evaluation, observation formatting, and memory proposal
    generation.

    It does not mutate TerminalState.
    """

    normalized = normalize_result(
        tool_name=tool_name,
        raw_result=raw_result,
        attempt=attempt,
    )

    _artifact_decision = evaluate_artifact_candidate(
        normalized,
    )

    formatted_observation = format_normalized_result(
        goal=state["goal"],
        normalized=normalized,
        artifact_decision=_artifact_decision,
    )

    proposal = condense_memory(
        goal=state["goal"],
        active_memory=format_active_memory(state["active_memory"]),
        formatted_observation=formatted_observation,
        tool_name=normalized.context.tool_name,
    )

    return RuntimeProcessingResult(
        normalized_result=normalized,
        artifact_decision=_artifact_decision,
        memory_update=proposal,
    )
