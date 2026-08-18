from agents.terminal.result_processing.models import (
    ArtifactCandidate,
    ExecutionOutcome,
    Fact,
    NormalizedResult,
    Resource,
    ToolExecutionContext,
)


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


def normalize_search_artifact(
    *,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> NormalizedResult:
    """
    Normalize search_artifact results.
    """

    print("\n========== SEARCH_ARTIFACT NORMALIZER ==========")
    print(raw_result)
    print(raw_result.get("success"))
    
    if not raw_result.get("success"):
        print("\nenter")
        return _build_normalized_result(
            tool_name=tool_name,
            attempt=attempt,
            success=False,
            progress_made=False,
            facts=[],
            resources=[],
            artifact=None,
        )

    query = raw_result["query"]
    count = raw_result["count"]
    artifact_id = raw_result["artifact_id"]

    facts = [
        Fact(
            statement=(
                f'Found {count} matches for "{query}" ' f'in artifact "{artifact_id}".'
            ),
            source=tool_name,
        ),
    ]

    if raw_result.get("truncated", False):
        facts.append(
            Fact(
                statement="Artifact search results were truncated.",
                source=tool_name,
            )
        )

    resources: list[Resource] = []

    for match in raw_result.get("matches", []):

        snippet = match.get("snippet", "").strip()

        # remove surrounding quotes
        snippet = snippet.strip('"')

        # artifact stores escaped backslashes
        snippet = snippet.replace("\\\\", "\\")

        resource_type = "directory" if "." not in snippet.split("\\")[-1] else "file"

        resources.append(
            Resource(
                type=resource_type,
                identifier=snippet,
                metadata={
                    "line": match.get("line"),
                },
            )
        )

    artifact = ArtifactCandidate(
        artifact_type="artifact_search_results",
        summary=(f'{count} matches for "{query}"'),
        data={
            "query": query,
            "matches": raw_result["matches"],
        },
    )
    
    if count == 0:
        progress_made = False
    else:
        progress_made = True
        
    dem = _build_normalized_result(
        tool_name=tool_name,
        attempt=attempt,
        success=True,
        progress_made=progress_made,
        facts=facts,
        resources=resources,
        artifact=artifact,
    )
    print("\n==========SEARCH RESULT==========")
    print(dem)

    return _build_normalized_result(
        tool_name=tool_name,
        attempt=attempt,
        success=True,
        progress_made=progress_made,
        facts=facts,
        resources=resources,
        artifact=artifact,
    )


def normalize_read_artifact(
    *,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> NormalizedResult:
    """
    Normalize read_artifact results.
    """
    print("\n========== READ_ARTIFACT NORMALIZER ==========")
    print(raw_result)

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

    artifact_id = raw_result["artifact_id"]

    start_line = raw_result["start_line"]
    end_line = raw_result["end_line"]

    facts = [
        Fact(
            statement=(f"Read artifact lines " f"(lines {start_line}-{end_line})."),
            source=tool_name,
        ),
    ]

    if raw_result.get("has_more", False):
        facts.append(
            Fact(
                statement="Additional artifact content is available.",
                source=tool_name,
            )
        )

    artifact = ArtifactCandidate(
        artifact_type="artifact_content",
        summary=(
            f"Contents of artifact "
            f"{artifact_id} "
            f"(lines {start_line}-{end_line})."
        ),
        data={
            "content": raw_result.get("content", ""),
            "artifact_id": artifact_id,
            "start_line": start_line,
            "end_line": end_line,
            "has_more": raw_result.get(
                "has_more",
                False,
            ),
        },
    )
    print("\n========== GENERATED ARTIFACT ==========")
    print(artifact)

    return _build_normalized_result(
        tool_name=tool_name,
        attempt=attempt,
        success=True,
        progress_made=True,
        facts=facts,
        resources=[],
        artifact=artifact,
    )
