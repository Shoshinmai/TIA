import uuid

from agents.terminal.memory.artifact import Artifact


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
