from agents.terminal.result_processing.models import (
    ArtifactCandidate,
    ExecutionOutcome,
    Fact,
    NormalizedResult,
    Resource,
    ResourceType,
    ToolExecutionContext,
)

from pathlib import Path


def _normalize_resource_path(
    path: str,
    project_root: str | None,
) -> str:
    """
    Normalize resource paths stored inside Active Memory.

    - Relative paths are preserved.
    - Absolute paths inside the project become project-relative.
    - External paths remain absolute.
    """

    candidate = Path(path)

    # Already relative → keep as-is
    if not candidate.is_absolute():
        return path

    if not project_root:
        return path

    try:
        return str(candidate.resolve().relative_to(Path(project_root).resolve()))

    except ValueError:
        return path


def _resource_depth(path: str) -> int:
    """
    Return directory depth of a resource.
    """

    return max(len(Path(path).parts) - 1, 0)


def _build_normalized_result(
    *,
    tool_name: str,
    attempt: int,
    success: bool,
    progress_made: bool,
    facts: list[Fact],
    resources: list[Resource],
    artifact: ArtifactCandidate | None,
) -> NormalizedResult:
    """
    Construct a NormalizedResult shared by filesystem
    discovery normalizers.
    """

    return NormalizedResult(
        context=ToolExecutionContext(
            tool_name=tool_name,
            attempt=attempt,
        ),
        execution=ExecutionOutcome(
            success=success,
            progress_made=progress_made,
            message=None,
        ),
        facts=facts,
        resources=resources,
        artifact=artifact,
    )


def _build_resource(
    *,
    identifier: str,
    project_root: str | None,
    resource_type: ResourceType,
    matched_query: bool = False,
) -> Resource:
    """
    Construct a filesystem Resource with consistent metadata.
    """

    normalized = _normalize_resource_path(
        identifier,
        project_root,
    )

    metadata = {
        "depth": _resource_depth(normalized),
    }

    if matched_query:
        metadata["matched_query"] = True

    return Resource(
        type=resource_type,
        identifier=normalized,
        metadata=metadata,
    )


def normalize_list_directory(
    *,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> NormalizedResult:
    """
    Normalize any filesystem listing result.

    Supports:
        - list_directory
        - search_files (later)
        - glob_files (later)
    """
    directories = raw_result.get("directories", [])
    files = raw_result.get("files", [])

    resources: list[Resource] = []
    project_root = raw_result.get("resolved_path")

    for directory in directories:
        resources.append(
            _build_resource(
                identifier=directory,
                project_root=project_root,
                resource_type=ResourceType.DIRECTORY,
            )
        )

    for file in files:
        resources.append(
            _build_resource(
                identifier=file,
                project_root=project_root,
                resource_type=ResourceType.FILE,
            )
        )

    facts = [
        Fact(
            statement=f"Found {raw_result['total_directories']} directories.",
            source=tool_name,
        ),
        Fact(
            statement=f"Found {raw_result['total_files']} files.",
            source=tool_name,
        ),
    ]

    artifact = ArtifactCandidate(
        artifact_type="file_listing",
        summary=(
            f"Filesystem listing containing "
            f"{raw_result['total_directories']} directories and {raw_result['total_files']} files."
        ),
        data=raw_result,
    )

    return _build_normalized_result(
        tool_name=tool_name,
        attempt=attempt,
        success=raw_result.get("success", False),
        progress_made=bool(resources),
        facts=facts,
        resources=resources,
        artifact=artifact,
    )


def normalize_search_files(
    *,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> NormalizedResult:
    """
    Normalize search_files results.

    Expected result:

    {
        "success": True,
        "query": "...",
        "matches": [
            "planner.py",
            "graph.py",
        ]
    }
    """
    project_root = raw_result.get("resolved_path")
    matches = raw_result.get("matches", [])

    resources = []

    for match in raw_result.get("matches", []):

        resources.append(
            _build_resource(
                identifier=match,
                project_root=project_root,
                resource_type=ResourceType.FILE,
                matched_query=True,
            )
        )

    facts = [
        Fact(
            statement=(
                f'Found {raw_result["count"]} files matching '
                f'"{raw_result["query"]}".'
            ),
            source=tool_name,
        )
    ]

    artifact = ArtifactCandidate(
        artifact_type="search_results",
        summary=(
            f'Search for "{raw_result["query"]}" '
            f'returned {raw_result["count"]} matching files.'
        ),
        data=raw_result,
    )

    return _build_normalized_result(
        tool_name=tool_name,
        attempt=attempt,
        success=raw_result.get("success", False),
        progress_made=bool(matches),
        facts=facts,
        resources=resources,
        artifact=artifact,
    )


def normalize_search_content(
    *,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> NormalizedResult:
    """
    Normalize search_content results.
    """

    matches = raw_result.get("matches", [])
    project_root = raw_result.get("resolved_path")
    seen: dict[str, Resource] = {}

    for match in raw_result.get("matches", []):

        resource = _build_resource(
            identifier=match["file"],
            project_root=project_root,
            resource_type=ResourceType.FILE,
            matched_query=True,
        )

        seen.setdefault(
            resource.identifier,
            resource,
        )

    resources = list(seen.values())

    facts = [
        Fact(
            statement=(f'Found "{raw_result["query"]}" ' f"in {len(resources)} files."),
            source=tool_name,
        )
    ]

    artifact = ArtifactCandidate(
        artifact_type="content_search",
        summary=(
            f'Content search for "{raw_result["query"]}" '
            f"found matches in {len(resources)} files."
        ),
        data=raw_result,
    )

    return _build_normalized_result(
        tool_name=tool_name,
        attempt=attempt,
        success=raw_result.get("success", False),
        progress_made=bool(resources),
        facts=facts,
        resources=resources,
        artifact=artifact,
    )

from agents.terminal.result_processing.models import (
    Fact,
    Resource,
    ResourceType,
)

def normalize_read_file(
    *,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> NormalizedResult:
    """
    Normalize read_file results.

    The normalizer preserves deterministic evidence:
    - file resource
    - complete raw read result
    - execution outcome

    Semantic information from the file contents is extracted
    later by the Memory Condenser.
    """

    if not raw_result.get("success", False):
        return _build_normalized_result(
            tool_name=tool_name,
            attempt=attempt,
            success=False,
            progress_made=False,
            facts=[],
            resources=[],
            artifact=None,
        )

    path = raw_result["path"]

    resource = _build_resource(
        identifier=path,
        project_root=None,
        resource_type=ResourceType.FILE,
    )

    start_line = raw_result["start_line"]
    end_line = raw_result["end_line"]

    artifact = ArtifactCandidate(
        artifact_type="file_content",
        summary=(
            f"Contents of {resource.identifier} "
            f"(lines {start_line}-{end_line})."
        ),
        data=raw_result,
    )

    return _build_normalized_result(
        tool_name=tool_name,
        attempt=attempt,
        success=True,
        progress_made=True,
        facts=[],
        resources=[resource],
        artifact=artifact,
    )
    
def normalize_get_file_info(
    *,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> NormalizedResult:
    """
    Normalize get_file_info results.
    """

    if not raw_result.get("success", False):
        return _build_normalized_result(
            tool_name=tool_name,
            attempt=attempt,
            success=False,
            progress_made=False,
            facts=[],
            resources=[],
            artifact=None,
        )

    path = raw_result["path"]
    item_type = raw_result["type"]

    resource_type = (
        ResourceType.DIRECTORY
        if item_type == "directory"
        else ResourceType.FILE
    )

    resource = _build_resource(
        identifier=path,
        project_root=None,
        resource_type=resource_type,
    )

    facts = [
        Fact(
            statement=f"{resource.identifier} is a {item_type}.",
            source=tool_name,
        ),
        Fact(
            statement=f"Size: {raw_result['size_bytes']} bytes.",
            source=tool_name,
        ),
    ]

    if raw_result.get("extension"):
        facts.append(
            Fact(
                statement=(
                    f'File extension: '
                    f'{raw_result["extension"]}.'
                ),
                source=tool_name,
            )
        )

    artifact = ArtifactCandidate(
        artifact_type="file_metadata",
        summary=(
            f"Metadata for {resource.identifier}."
        ),
        data=raw_result,
    )

    return _build_normalized_result(
        tool_name=tool_name,
        attempt=attempt,
        success=True,
        progress_made=True,
        facts=facts,
        resources=[resource],
        artifact=artifact,
    )