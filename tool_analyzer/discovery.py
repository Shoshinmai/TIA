
from __future__ import annotations

from collections import OrderedDict
from pathlib import PurePosixPath
from typing import Any

from models import SearchFilesResult
from tool_analyzer.discovery_models import (
    DiscoveryAnalysis,
    DiscoveryDirectoryGroup,
)


DISCLOSED_PATH_LIMIT = 10


def analyze_search_files_result(
    raw_result: Any,
    *,
    source_artifact_id: str | None = None,
) -> DiscoveryAnalysis:
    """Build a deterministic, compact representation of search_files output.

    The original result is never modified. It remains available through
    ArtifactStore; this function only creates a bounded representation.
    """

    result = SearchFilesResult.model_validate(raw_result)

    # The source contract says returned_count describes the actual
    # number of match objects returned. Reject inconsistent payloads.
    if result.returned_count != len(result.matches):
        raise ValueError(
            "Invalid search_files result: returned_count "
            f"({result.returned_count}) does not match the number "
            f"of returned matches ({len(result.matches)})."
        )

    disclosed_paths = result.matches[:DISCLOSED_PATH_LIMIT]

    # Preserve the first occurrence of each directory in ranked order.
    # Counts represent files directly inside that directory only.
    directory_counts: OrderedDict[str, int] = OrderedDict()

    for match in result.matches:
        directory = PurePosixPath(match.relative_path).parent.as_posix()
        directory_counts[directory] = directory_counts.get(directory, 0) + 1

    directory_groups = [
        DiscoveryDirectoryGroup(
            directory=directory,
            match_count=count,
        )
        for directory, count in directory_counts.items()
    ]

    return DiscoveryAnalysis(
        success=result.success,
        query=result.query,
        root=result.root,
        disclosed_paths=disclosed_paths,
        directory_groups=directory_groups,
        returned_count=result.returned_count,
        undisclosed_returned_count=(
            result.returned_count - len(disclosed_paths)
        ),
        total_matches=result.total_matches,
        complete=result.complete,
        truncated=result.truncated,
        limit_reached=result.limit_reached,
        traversal_errors=result.traversal_errors,
        skipped_symlinks=result.skipped_symlinks,
        error=result.error,
        source_artifact_id=source_artifact_id,
    )


def format_discovery_analysis(
    analysis: DiscoveryAnalysis,
) -> str:
    """Render DiscoveryAnalysis as a compact Main Agent observation."""

    lines = [
        "Discovery analysis: search_files",
        f"Query: {analysis.query}",
        f"Search success: {analysis.success}",
    ]

    if analysis.root:
        lines.append(f"Search root: {analysis.root}")

    lines.append(f"Returned matches: {analysis.returned_count}")

    coverage = "complete" if analysis.complete else "incomplete"
    lines.append(f"Traversal coverage: {coverage}")

    if analysis.complete:
        lines.append(f"Total matches: {analysis.total_matches}")
    else:
        lines.append(
            "Matches found in traversed area: "
            f"{analysis.total_matches} (not an exact total)"
        )

    if analysis.truncated:
        lines.append("Results were truncated.")

    if analysis.limit_reached:
        lines.append(f"Limit or stopping reason: {analysis.limit_reached}")

    if analysis.error:
        lines.append(f"Search error: {analysis.error}")

    if analysis.disclosed_paths:
        lines.append("")
        lines.append(
            f"Top ranked paths (showing {len(analysis.disclosed_paths)}):"
        )

        for index, match in enumerate(analysis.disclosed_paths, start=1):
            lines.append(
                f"{index}. {match.relative_path} "
                f"[{match.match_type}, {match.matched_on}, "
                f"score={match.score:g}]"
            )

    if analysis.undisclosed_returned_count:
        lines.append(
            f"{analysis.undisclosed_returned_count} additional returned "
            "matches are not listed here; retrieve the original artifact "
            "to inspect them."
        )

    if analysis.directory_groups:
        lines.append("")
        lines.append("Matching files by directory:")

        for group in analysis.directory_groups:
            lines.append(
                f"{group.directory}/ ({group.match_count})"
                if group.directory != "."
                else f"./ ({group.match_count})"
            )

    if analysis.traversal_errors:
        lines.append("")
        lines.append("Traversal errors:")
        lines.extend(
            f"- {error}" for error in analysis.traversal_errors
        )

    if analysis.skipped_symlinks:
        lines.append(
            f"Skipped symbolic links: {analysis.skipped_symlinks}"
        )

    if analysis.source_artifact_id:
        lines.append(
            "Original result artifact: "
            f"{analysis.source_artifact_id}"
        )

    return "\n".join(lines)
