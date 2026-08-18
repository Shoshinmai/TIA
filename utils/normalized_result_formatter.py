from typing import List

from agents.terminal.result_processing.models import (
    ArtifactAction,
    ArtifactDecision,
    NormalizedResult,
)
from agents.terminal.utils.resource_ranker import rank_resources


MAX_DISPLAYED_RESOURCES = 10

# Maximum size of the formatted observation sent to the
# Memory Condenser.
MAX_INLINE_OBSERVATION_CHARS = 6000
SAFETY_MARGIN = 200
INLINE_CONTENT_TOOLS = {
    "read_file",
    "read_artifact",
    "run_terminal",
    "search_artifact",
}


def _append_content_section(
    *,
    lines: list[str],
    title: str,
    content: str,
) -> None:
    """
    Append textual content to the formatted observation.

    Small observations are embedded directly so the Memory
    Condenser can reason over them.

    Larger observations are truncated deterministically while
    the complete content remains available inside the artifact.
    """

    if not content:
        return

    # --------------------------------------------------
    # Remaining formatter budget
    # --------------------------------------------------

    current_size = len("\n".join(lines))

    remaining_budget = MAX_INLINE_OBSERVATION_CHARS - current_size - SAFETY_MARGIN

    if remaining_budget <= 0:
        return

    lines.append("")
    lines.append(f"{title}:")

    if len(content) <= remaining_budget:

        lines.append(content)
        return

    lines.append(content[:remaining_budget])

    lines.append("")
    lines.append("[Content truncated]")
    lines.append("Complete content is available in the stored artifact.")


def format_normalized_result(
    goal: str,
    normalized: NormalizedResult,
    artifact_decision: ArtifactDecision,
) -> str:
    """
    Convert a NormalizedResult into a concise LLM-friendly
    observation for the Memory Condenser.

    Large observations remain summarized through artifacts,
    while naturally bounded observations (for example
    read_file/read_artifact) expose their content directly so
    semantic reasoning can occur.
    """

    lines: List[str] = []

    # --------------------------------------------------
    # Tool
    # --------------------------------------------------

    lines.append(f"Tool: {normalized.context.tool_name}")
    
    if normalized.context.tool_name == "run_terminal":

        execution = normalized.execution

        lines.append("")
        lines.append("Execution:")

        lines.append(
            f"- Success: {execution.success}"
        )

        lines.append(
            f"- Return code: {execution.return_code}"
        )

    # --------------------------------------------------
    # Facts
    # --------------------------------------------------

    if normalized.facts:

        lines.append("")
        lines.append("Facts:")

        for fact in normalized.facts:
            lines.append(f"- {fact.statement}")

    # --------------------------------------------------
    # Resources
    # --------------------------------------------------

    if normalized.resources:

        total = len(normalized.resources)

        lines.append("")
        lines.append(f"Resources ({total} discovered):")

        ranked_resources = rank_resources(
            goal=goal,
            tool_name=normalized.context.tool_name,
            resources=normalized.resources,
        )

        for ranked in ranked_resources[:MAX_DISPLAYED_RESOURCES]:

            resource = ranked.resource

            lines.append(
                f"- ({ranked.score}) "
                f"[{resource.type.value}] "
                f"{resource.identifier}"
            )

        remaining = total - MAX_DISPLAYED_RESOURCES

        if remaining > 0:

            lines.append(f"... and {remaining} more resources.")

    # --------------------------------------------------
    # Artifact
    # --------------------------------------------------

    lines.append("")
    lines.append("Artifact:")

    if artifact_decision.action == ArtifactAction.STORE:

        lines.append("Stored")

        artifact = artifact_decision.artifact

        if artifact is not None:

            lines.append(f"Summary: {artifact.summary}")

            # ------------------------------------------
            # Inline bounded observations
            # ------------------------------------------

            if normalized.context.tool_name in INLINE_CONTENT_TOOLS and isinstance(
                artifact.data,
                dict,
            ):
                content = _extract_inline_content(
                    tool_name=normalized.context.tool_name,
                    artifact_data=artifact.data,
                )

                _append_content_section(
                    lines=lines,
                    title="Content",
                    content=content,
                )

            if normalized.context.tool_name == "run_terminal":
                if isinstance(artifact.data, dict):
                    error = str(
                        artifact.data.get(
                            "error",
                            "",
                        )
                    )

                    _append_terminal_error(
                        lines=lines,
                        error=error,
                    )

        # Large observations still rely on artifacts.

        if normalized.context.tool_name not in INLINE_CONTENT_TOOLS:

            lines.append(
                "Complete resource list is available "
                "from the artifact if additional "
                "details are required."
            )

    else:

        lines.append("Not Stored")

    return "\n".join(lines)


def _extract_inline_content(
    *,
    tool_name: str,
    artifact_data: object,
) -> str:
    """
    Extract human-readable inline content from a normalized
    artifact.

    The artifact schema remains tool-faithful while this helper
    provides a common presentation layer.
    """

    if not isinstance(
        artifact_data,
        dict,
    ):
        return ""

    if tool_name in {
        "read_file",
        "read_artifact",
    }:
        return str(
            artifact_data.get(
                "content",
                "",
            )
        )

    if tool_name == "run_terminal":
        return str(
            artifact_data.get(
                "output",
                "",
            )
        )

    return ""


def _append_terminal_error(
    *,
    lines: list[str],
    error: str,
) -> None:
    if not error:
        return

    _append_content_section(
        lines=lines,
        title="Error",
        content=error,
    )
