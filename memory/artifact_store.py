from typing import Any
import uuid

from memory.artifact import Artifact


class ArtifactStore:

    def __init__(self):

        self._store = {}

    def save(self, artifact_type, summary, data, metadata=None):

        artifact_id = str(uuid.uuid4())

        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            summary=summary,
            data=data,
            metadata=metadata or {},
        )
        self._store[artifact_id] = artifact

        return artifact_id

    def get(self, artifact_id):

        return self._store.get(artifact_id)

    def get_all(self):

        return list(self._store.values())

    def get_catalog(
        self,
        artifact_ids: list[str] | None = None,
    ) -> list[dict]:
        """
        Return compact metadata for stored artifacts.

        Args:
            artifact_ids:
                Optional list of artifact IDs to include.
                If omitted, all stored artifacts are included.

        Returns:
            Compact artifact metadata suitable for planner context.
        """

        if artifact_ids is None:
            artifacts = self.get_all()

        else:
            artifacts = []

            for artifact_id in artifact_ids:

                artifact = self.get(artifact_id)

                if artifact is not None:
                    artifacts.append(artifact)

        return [
            {
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "summary": artifact.summary,
            }
            for artifact in artifacts
        ]
    def save_tool_result(
    self,
    *,
    tool_name: str,
    result: Any,
    sequence: int,
    action_signature: str | None = None,
    ) -> str:
        """Store the original tool result without replacing it with a summary."""
        metadata = {
            "source": "agentic_loop",
            "tool_name": tool_name,
            "sequence": sequence,
        }

        if action_signature:
            metadata["action_signature"] = action_signature

        if isinstance(result, dict) and "success" in result:
            metadata["success"] = bool(result["success"])

        return self.save(
            artifact_type="tool_result",
            summary=(
                f"Original result from capability '{tool_name}' "
                f"(observation {sequence})."
            ),
            data=result,
            metadata=metadata,
        )