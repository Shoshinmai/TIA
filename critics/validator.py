from agents.terminal.critics.models import CriticOutput


def validate_critic_output(
    critic_output: CriticOutput,
) -> CriticOutput:
    """
    Deterministically validate the semantic contract of a
    CriticOutput.

    This function does not decide whether the Critic's decision
    is correct. It only verifies that the output contains the
    information required to safely pass the decision to the
    runtime layer.
    """

    if not critic_output.rationale.strip():
        raise ValueError(
            "CriticOutput rationale cannot be empty."
        )

    if not critic_output.evidence:
        raise ValueError(
            "CriticOutput must contain at least one "
            "piece of evidence."
        )

    for index, evidence in enumerate(
        critic_output.evidence
    ):
        if not evidence.source.strip():
            raise ValueError(
                f"Critic evidence at index {index} "
                "has an empty source."
            )

        if not evidence.observation.strip():
            raise ValueError(
                f"Critic evidence at index {index} "
                "has an empty observation."
            )

    return critic_output