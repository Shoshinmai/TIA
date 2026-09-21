from result_processing.memory_condenser import (
    condense_memory,
)

from result_processing.models import (
    MemoryUpdateProposal,
    RuntimeProcessingResult,
)

from state import TerminalState

from result_processing.normalizer import (
    normalize_result,
)

from result_processing.artifact_policy import (
    evaluate_artifact_candidate,
)

from utils.memory_formatter import (
    format_active_memory,
)

from utils.normalized_result_formatter import (
    format_normalized_result,
)


async def process_tool_result(
    *,
    state: TerminalState,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> RuntimeProcessingResult:
    """
    Process a raw tool result through the Runtime Processing Pipeline.

    This function is responsible for:

    - normalization
    - artifact policy evaluation
    - observation formatting
    - memory proposal generation

    It does not mutate TerminalState.

    Memory condensation failure must not discard the already
    normalized execution result or artifact decision.
    """

    # ==========================================================
    # 1. Normalize raw result
    # ==========================================================

    normalized = normalize_result(
        tool_name=tool_name,
        raw_result=raw_result,
        attempt=attempt,
    )

    # ==========================================================
    # 2. Evaluate artifact policy
    # ==========================================================

    artifact_decision = evaluate_artifact_candidate(
        normalized,
    )

    # ==========================================================
    # 3. Build semantic observation
    # ==========================================================

    formatted_observation = format_normalized_result(
        goal=state["goal"],
        normalized=normalized,
        artifact_decision=artifact_decision,
    )

    # ==========================================================
    # 4. Generate Active Memory proposal
    # ==========================================================
    #
    # Memory condensation is downstream of normalization.
    #
    # If the condenser fails, the normalized result and artifact
    # decision are still valid and must continue through the
    # Runtime Processing Pipeline.
    #
    # The failure therefore produces an empty proposal rather
    # than destroying the complete processing result.
    # ==========================================================

    proposal = await condense_memory(
        goal=state["goal"],
        active_memory=format_active_memory(
            state["active_memory"],
        ),
        formatted_observation=formatted_observation,
        tool_name=normalized.context.tool_name,
    )

    # ==========================================================
    # 5. Return complete RuntimeProcessingResult
    # ==========================================================

    return RuntimeProcessingResult(
        normalized_result=normalized,
        artifact_decision=artifact_decision,
        memory_update=proposal,
    )