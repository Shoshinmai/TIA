
from __future__ import annotations

from collections import OrderedDict
from pathlib import PurePosixPath
from typing import Any

from models import ListDirectoryResult, SearchFilesResult
from tool_analyzer.discovery_models import (
    DirectoryListingAnalysis,
    DirectoryTreeEntry,
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


def analyze_list_directory_result(
    raw_result: Any,
    *,
    source_artifact_id: str | None = None,
) -> DirectoryListingAnalysis:
    """Build a complete parent-linked representation of list_directory output.

    Every returned path is represented. No ranking, sampling, or
    disclosure limit is applied.

    The original result is never modified.
    """

    result = ListDirectoryResult.model_validate(raw_result)

    if result.returned_directories != len(result.directories):
        raise ValueError(
            "Invalid list_directory result: returned_directories "
            f"({result.returned_directories}) does not match the number "
            f"of returned directories ({len(result.directories)})."
        )

    if result.returned_files != len(result.files):
        raise ValueError(
            "Invalid list_directory result: returned_files "
            f"({result.returned_files}) does not match the number "
            f"of returned files ({len(result.files)})."
        )

    root = result.resolved_path
    if not root:
        raise ValueError(
            "Cannot analyze list_directory result without resolved_path."
        )

    entries: list[DirectoryTreeEntry] = []
    directory_ids: dict[str, str] = {}

    def parse_relative_path(path: str) -> PurePosixPath:
        relative = PurePosixPath(path)

        if (
            not path
            or relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative == PurePosixPath(".")
        ):
            raise ValueError(
                f"Invalid relative path in list_directory result: {path!r}"
            )

        return relative

    # ----------------------------------------------------------
    # Directories
    # ----------------------------------------------------------

    for directory in result.directories:
        relative = parse_relative_path(directory)
        parent_path = relative.parent.as_posix()

        if parent_path == ".":
            parent_id = "ROOT"
        else:
            parent_id = directory_ids.get(parent_path)

            if parent_id is None:
                raise ValueError(
                    "Invalid list_directory hierarchy: parent directory "
                    f"{parent_path!r} was not returned before "
                    f"child directory {directory!r}."
                )

        entry_id = f"D{len(directory_ids)}"

        entries.append(
            DirectoryTreeEntry(
                id=entry_id,
                name=relative.name,
                parent_id=parent_id,
                entry_type="directory",
            )
        )

        directory_ids[relative.as_posix()] = entry_id

    # ----------------------------------------------------------
    # Files
    # ----------------------------------------------------------

    for file in result.files:
        relative = parse_relative_path(file)
        parent_path = relative.parent.as_posix()

        if parent_path == ".":
            parent_id = "ROOT"
        else:
            parent_id = directory_ids.get(parent_path)

            if parent_id is None:
                raise ValueError(
                    "Invalid list_directory hierarchy: parent directory "
                    f"{parent_path!r} was not returned for file {file!r}."
                )

        entry_id = f"F{sum(
            entry.entry_type == "file" for entry in entries
        )}"

        entries.append(
            DirectoryTreeEntry(
                id=entry_id,
                name=relative.name,
                parent_id=parent_id,
                entry_type="file",
            )
        )

    return DirectoryListingAnalysis(
        success=result.success,
        root=root,
        entries=entries,
        returned_directories=result.returned_directories,
        returned_files=result.returned_files,
        total_directories=result.total_directories,
        total_files=result.total_files,
        recursive=result.recursive,
        complete=result.complete,
        truncated=result.truncated,
        limit_reached=result.limit_reached,
        traversal_errors=result.traversal_errors,
        skipped_symlinks=result.skipped_symlinks,
        error=result.error,
        source_artifact_id=source_artifact_id,
    )


def format_list_directory_analysis(
    analysis: DirectoryListingAnalysis,
) -> str:
    """Render the complete directory tree as a compact Main Agent observation."""

    lines = [
        "Discovery analysis: list_directory",
        f"Root: {analysis.root}",
        f"Listing success: {analysis.success}",
        "",
        "DIRECTORY TREE",
        "ROOT",
    ]

    for entry in analysis.entries:
        lines.append(
            f"{entry.id} <- {entry.parent_id}: {entry.name}"
        )

    lines.extend(
        [
            "",
            "LISTING SUMMARY",
            f"Returned directories: {analysis.returned_directories}",
            f"Returned files: {analysis.returned_files}",
            f"Returned entries: {len(analysis.entries)}",
            f"Recursive: {analysis.recursive}",
        ]
    )

    if analysis.complete:
        lines.extend(
            [
                "Coverage: complete",
                f"Total directories: {analysis.total_directories}",
                f"Total files: {analysis.total_files}",
            ]
        )
    else:
        lines.extend(
            [
                "Coverage: INCOMPLETE",
                (
                    "Directories discovered in traversed area: "
                    f"{analysis.total_directories} (not an exact total)"
                ),
                (
                    "Files discovered in traversed area: "
                    f"{analysis.total_files} (not an exact total)"
                ),
                (
                    "WARNING: Do not assume that entries absent from "
                    "this tree do not exist."
                ),
            ]
        )

    if analysis.truncated:
        lines.append("Listing was truncated.")

    if analysis.limit_reached:
        lines.append(f"Stopping reason: {analysis.limit_reached}")

    if analysis.error:
        lines.append(f"Listing error: {analysis.error}")

    if analysis.traversal_errors:
        lines.append("")
        lines.append("TRAVERSAL ERRORS")
        lines.extend(
            f"- {error}" for error in analysis.traversal_errors
        )

    if analysis.skipped_symlinks:
        lines.append(
            f"Skipped symbolic links: {analysis.skipped_symlinks}"
        )

    if analysis.source_artifact_id:
        lines.append(
            f"Original result artifact: {analysis.source_artifact_id}"
        )

    return "\n".join(lines)
