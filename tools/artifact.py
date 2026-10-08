from __future__ import annotations

from langchain_core.tools import tool

from memory import artifact_retriever
from models import (
    ReadArtifactInput,
    SearchArtifactInput,
)


@tool(args_schema=SearchArtifactInput)
async def search_artifact(
    artifact_id: str,
    query: str,
    case_sensitive: bool = False,
    max_results: int = 50,
) -> dict:
    """
    Search for text within a stored artifact.

    This capability searches an already-created artifact.
    Artifact retrieval is currently an in-memory synchronous
    operation; the tool itself exposes an async boundary so
    ToolNode can execute the entire tool surface uniformly.
    """

    return artifact_retriever.search(
        artifact_id=artifact_id,
        query=query,
        case_sensitive=case_sensitive,
        max_results=max_results,
    )


@tool(args_schema=ReadArtifactInput)
async def read_artifact(
    artifact_id: str,
    start_line: int = 1,
    max_lines: int = 200,
) -> dict:
    """
    Read a bounded section of a stored artifact.

    Artifact retrieval is currently an in-memory synchronous
    operation; the tool exposes an async interface for the
    runtime's unified async tool boundary.
    """

    return artifact_retriever.read(
        artifact_id=artifact_id,
        start_line=start_line,
        max_lines=max_lines,
    )