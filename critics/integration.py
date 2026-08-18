from pydantic import BaseModel

from agents.terminal.critics.models import (
    CriticOutput,
)

from agents.terminal.runtime.events import (
    RuntimeEvent,
)

from agents.terminal.runtime.models import (
    RuntimeDecisionContext,
    RuntimeEvidence,
)


def critic_output_to_runtime_event(
    critic_output: CriticOutput,
) -> RuntimeEvent:
    """
    Convert a validated CriticOutput into the corresponding
    RuntimeEvent.

    This function performs no routing or orchestration.
    """

    decision = critic_output.decision

    try:
        return RuntimeEvent(
            decision.value,
        )

    except ValueError as exc:
        raise ValueError(
            f"Critic decision '{decision.value}' does not "
            "have a corresponding RuntimeEvent."
        ) from exc


def critic_output_to_runtime_context(
    critic_output: CriticOutput,
) -> RuntimeDecisionContext:
    """
    Convert Critic-owned rationale and evidence into the
    runtime-neutral decision context.
    """

    return RuntimeDecisionContext(
        rationale=critic_output.rationale,
        evidence=[
            RuntimeEvidence(
                source=evidence.source,
                observation=evidence.observation,
            )
            for evidence in critic_output.evidence
        ],
    )


class CriticRuntimeEvent(BaseModel):
    """
    Runtime-facing representation of a Critic decision.

    This model intentionally contains only Runtime-owned data.

    The Critic subsystem owns CriticOutput.
    The Runtime receives:
        - the normalized RuntimeEvent
        - the RuntimeDecisionContext
    """

    event: RuntimeEvent

    context: RuntimeDecisionContext


def build_critic_runtime_event(
    critic_output: CriticOutput,
) -> CriticRuntimeEvent:
    """
    Convert validated Critic output into the complete
    runtime-facing decision contract.
    """

    return CriticRuntimeEvent(
        event=critic_output_to_runtime_event(
            critic_output,
        ),
        context=critic_output_to_runtime_context(
            critic_output,
        ),
    )