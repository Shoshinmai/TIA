from agents.terminal.result_processing.models import (
    ArtifactAction,
    ArtifactDecision,
    NormalizedResult,
)


def evaluate_artifact_candidate(
    normalized: NormalizedResult,
) -> ArtifactDecision:
    """
    Decide whether a normalized result should be stored as an artifact.

    This function is deterministic and does not perform storage.
    """

    if normalized.artifact is None:
        return ArtifactDecision(
            action=ArtifactAction.SKIP,
            reason="No artifact candidate produced.",
            artifact=None,
        )

    return ArtifactDecision(
        action=ArtifactAction.STORE,
        reason="Artifact candidate available.",
        artifact=normalized.artifact,
    )