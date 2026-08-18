from agents.terminal.result_processing.models import (
    ArtifactCandidate,
    ExecutionOutcome,
    Fact,
    NormalizedResult,
    ToolExecutionContext,
)


def _build_normalized_result(
    *,
    tool_name: str,
    attempt: int,
    success: bool,
    progress_made: bool,
    facts: list[Fact],
    artifact: ArtifactCandidate | None,
) -> NormalizedResult:
    """
    Construct a NormalizedResult for execution capabilities.
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
        resources=[],
        artifact=artifact,
    )


def normalize_run_terminal(
    *,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> NormalizedResult:

    success = bool(
        raw_result.get(
            "success",
            False,
        )
    )

    return_code = raw_result.get(
        "return_code",
    )

    output = str(
        raw_result.get(
            "output",
            "",
        )
        or ""
    )

    error = str(
        raw_result.get(
            "error",
            "",
        )
        or ""
    )

    # ----------------------------------------------------------
    # Semantic execution outcome
    # ----------------------------------------------------------

    execution = ExecutionOutcome(
        success=success,
        progress_made=success,
        message=(
            "Terminal command completed successfully."
            if success
            else "Terminal command failed."
        ),
        return_code=return_code,
        stdout=output,
        stderr=error,
    )

    # ----------------------------------------------------------
    # Preserve complete terminal evidence as an artifact.
    # ----------------------------------------------------------

    artifact = ArtifactCandidate(
        artifact_type="terminal_output",
        summary=(
            "Terminal command output."
            if success
            else "Terminal command failed."
        ),
        data={
            "output": output,
            "error": error,
            "return_code": return_code,
        },
    )

    return NormalizedResult(
        context=ToolExecutionContext(
            tool_name=tool_name,
            attempt=attempt,
        ),
        resources=[],
        facts=[],
        execution=execution,
        artifact=artifact,
    )