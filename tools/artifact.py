from langchain_core.tools import tool

from agents.terminal.memory import artifact_retriever
from agents.terminal.models import ReadArtifactInput, SearchArtifactInput


@tool(args_schema=SearchArtifactInput)
def search_artifact(
    artifact_id: str,
    query: str,
    case_sensitive: bool = False,
    max_results: int = 50,
) -> dict:
    """
    Search for text within a stored artifact.

    PURPOSE
    -------
    Find specific information inside an artifact previously
    created from a large tool observation.

    Use this capability when the required information may exist
    inside an artifact listed in Available Artifacts.

    Typical use cases:

    - Search large filesystem listings stored as artifacts.
    - Search command outputs stored as artifacts.
    - Search logs or other large text observations.
    - Locate specific filenames, paths, errors, symbols, or text
      inside previously stored artifact data.
    - Reuse existing artifact information instead of repeating
      an expensive tool operation.

    Use this capability when:

    - A relevant artifact already exists.
    - The complete artifact is too large to inspect directly.
    - You need to locate specific information inside an artifact.

    Do NOT use this capability when:

    - No relevant artifact exists.
    - You need to inspect a known bounded section of an artifact;
      use read_artifact instead.
    - You need fresh filesystem or system information that may
      have changed since the artifact was created.

    Args:
        artifact_id:
            Unique identifier of the artifact to search.

        query:
            Text to search for inside the artifact.

        case_sensitive:
            Whether matching should respect letter case.

        max_results:
            Maximum number of matching results to return.

    Returns:
        Structured search results from the requested artifact.
    """

    return artifact_retriever.search(
        artifact_id=artifact_id,
        query=query,
        case_sensitive=case_sensitive,
        max_results=max_results,
    )
    
@tool(args_schema=ReadArtifactInput)
def read_artifact(
    artifact_id: str,
    start_line: int = 1,
    max_lines: int = 200,
) -> dict:
    """
    Read a bounded section of a stored artifact.

    PURPOSE
    -------
    Inspect a specific line window from an artifact previously
    created from a large tool observation.

    This capability provides paginated access to artifact data
    without loading the complete artifact into the agent context.

    TYPICAL USE CASES
    -----------------
    - Read a specific section of a large filesystem listing.
    - Inspect part of a stored command output.
    - Read surrounding information after locating relevant lines
      with search_artifact.
    - Continue reading an artifact using next_start_line.
    - Reuse stored observations instead of repeating expensive
      tool operations.

    USE THIS CAPABILITY WHEN
    ------------------------
    - A relevant artifact already exists.
    - The artifact ID is known.
    - You need to inspect a bounded section of the artifact.
    - search_artifact identified relevant serialized line numbers.
    - A previous read_artifact result returned has_more=True.

    DO NOT USE THIS CAPABILITY WHEN
    --------------------------------
    - You need to locate specific information inside a large
      artifact. Use search_artifact first.

    - No relevant artifact exists.

    - You need fresh filesystem or system information that may
      have changed since the artifact was created.

    IMPORTANT
    ---------
    start_line refers to the serialized artifact representation,
    not necessarily to line numbers in an original source file.

    Use next_start_line from the result to continue reading the
    artifact without overlapping or skipping content.

    Args:
        artifact_id:
            Unique identifier of the artifact to read.

        start_line:
            First serialized artifact line to read.
            Lines are 1-indexed.

        max_lines:
            Maximum number of serialized artifact lines to return.

    Returns:
        Structured artifact content with pagination metadata.
    """

    return artifact_retriever.read(
        artifact_id=artifact_id,
        start_line=start_line,
        max_lines=max_lines,
    )