from agents.terminal.result_processing.models import (
    ArtifactAction,
    ArtifactDecision,
    NormalizedResult,
)


def build_evaluator_observation(
    *,
    normalized_result: NormalizedResult,
    artifact_decision: ArtifactDecision,
) -> str:
    """
    Build a compact semantic report of the latest execution.

    This report is intended for the Evaluator. It summarizes the
    semantic outcome of the latest tool execution without exposing
    the raw tool output.
    """

    execution = normalized_result.execution

    lines: list[str] = []

    lines.append("Latest Execution")
    lines.append("----------------")

    lines.append(
        f"Tool: {normalized_result.context.tool_name}"
    )

    lines.append(
        f"Success: {'Yes' if execution.success else 'No'}"
    )

    lines.append(
        f"Progress Made: {'Yes' if execution.progress_made else 'No'}"
    )

    lines.append(
        f"Outcome: {execution.message or 'No execution summary available.'}"
    )

    lines.append(
        f"Resources Discovered: {len(normalized_result.resources)}"
    )

    lines.append(
        f"Facts Extracted: {len(normalized_result.facts)}"
    )

    lines.append(
        "Artifact Created: "
        + (
            "Yes"
            if artifact_decision.action == ArtifactAction.STORE
            else "No"
        )
    )

    if artifact_decision.reason:
        lines.append(
            f"Artifact Decision: {artifact_decision.reason}"
        )

    return "\n".join(lines)