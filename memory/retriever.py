from agents.terminal.memory.artifact_store import ArtifactStore, Artifact

import json
from typing import Any


def serialize_artifact_data(data: Any) -> str:
    """
    Convert artifact data into a stable text representation.

    This provides a common representation for artifact searching
    and bounded reading regardless of the original data structure.

    Args:
        data:
            Raw artifact data.

    Returns:
        A text representation of the artifact data.
    """

    if isinstance(data, str):
        return data

    try:
        return json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    except (TypeError, ValueError):
        return str(data)


class ArtifactRetriever:

    def __init__(
        self,
        artifact_store: ArtifactStore,
    ):
        self.artifact_store = artifact_store

    def get_artifact(
        self,
        artifact_id: str,
    ) -> Artifact:
        """
        Retrieve an artifact by ID.

        Args:
            artifact_id:
                Unique identifier of the artifact.

        Returns:
            The matching Artifact.

        Raises:
            ValueError:
                If artifact_id is empty or the artifact
                does not exist.
        """

        if not artifact_id:
            raise ValueError("artifact_id cannot be empty.")

        artifact = self.artifact_store.get(artifact_id)

        if artifact is None:
            raise ValueError(f"Artifact not found: {artifact_id}")

        return artifact

    def search(
        self,
        artifact_id: str,
        query: str,
        case_sensitive: bool = False,
        max_results: int = 50,
    ) -> dict:
        """
        Search for text within an artifact.

        The artifact data is converted to a stable text representation
        before searching.

        Args:
            artifact_id:
                Unique identifier of the artifact.

            query:
                Text to search for.

            case_sensitive:
                Whether matching should respect letter case.

            max_results:
                Maximum number of matches to return.

        Returns:
            Structured search results containing matching line numbers
            and snippets.
        """

        if not query:
            raise ValueError("query cannot be empty.")

        if max_results < 1:
            raise ValueError("max_results must be at least 1.")

        artifact = self.get_artifact(artifact_id)

        text = serialize_artifact_data(artifact.data)

        search_query = query if case_sensitive else query.lower()

        matches = []
        truncated = False

        for line_number, line in enumerate(
            text.splitlines(),
            start=1,
        ):
            search_line = line if case_sensitive else line.lower()

            if search_query not in search_line:
                continue

            if len(matches) >= max_results:
                truncated = True
                break

            matches.append(
                {
                    "line": line_number,
                    "snippet": line.strip(),
                }
            )

        try:
            return {
                "success": True,
                "artifact_id": artifact_id,
                "query": query,
                "count": len(matches),
                "matches": matches,
                "truncated": truncated,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def read(
        self,
        artifact_id: str,
        start_line: int = 1,
        max_lines: int = 200,
    ) -> dict:
        """
        Read a bounded window of lines from an artifact.

        The artifact data is converted to a stable text representation
        before reading.

        Args:
            artifact_id:
                Unique identifier of the artifact.

            start_line:
                First serialized artifact line to read.
                Lines are 1-indexed.

            max_lines:
                Maximum number of lines to return.

        Returns:
            Structured artifact content with pagination metadata.
        """

        if start_line < 1:
            raise ValueError("start_line must be at least 1.")

        if max_lines < 1:
            raise ValueError("max_lines must be at least 1.")

        artifact = self.get_artifact(artifact_id)

        text = serialize_artifact_data(artifact.data)

        lines = text.splitlines()

        start_index = start_line - 1
        end_index = start_index + max_lines

        selected_lines = lines[start_index:end_index]

        lines_returned = len(selected_lines)

        if lines_returned > 0:
            end_line = start_line + lines_returned - 1
        else:
            end_line = None

        has_more = end_index < len(lines)

        next_start_line = end_line + 1 if has_more else None

        try:
            return {
                "success": True,
                "artifact_id": artifact_id,
                "artifact_type": artifact.artifact_type,
                "summary": artifact.summary,
                "start_line": start_line,
                "end_line": end_line,
                "lines_returned": lines_returned,
                "has_more": has_more,
                "next_start_line": next_start_line,
                "content": "\n".join(selected_lines),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    # @staticmethod
    # def find_file(artifact_id: str, filename: str):

    #     artifact = artifact_store.get(artifact_id)

    #     if not artifact:
    #         return []

    #     matches = []

    #     for file in artifact.data:

    #         if filename.lower() in file.lower():
    #             matches.append(file)

    #     return matches

    # @staticmethod
    # def count_entries(artifact_id: str):

    #     artifact = artifact_store.get(artifact_id)

    #     if not artifact:
    #         return 0

    #     return len(artifact.data)
