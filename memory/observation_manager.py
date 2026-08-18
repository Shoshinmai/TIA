from agents.terminal.memory import artifact_store
from agents.terminal.memory.execution_manager import (
    ExecutionMemoryManager,
)
from agents.terminal.result_processing.models import (
    ArtifactAction,
)
from agents.terminal.result_processing.state_mutator import (
    mutate_state,
)
from agents.terminal.state import TerminalState


def observation_manager_node(
    state: TerminalState,
):
    processed = state.get(
        "runtime_processing_result"
    )

    if processed is None:
        raise RuntimeError(
            "RuntimeProcessingResult missing."
        )

    # ------------------------------------------
    # Persist artifact if requested
    # ------------------------------------------

    artifact_ids = list(
        state.get(
            "artifact_ids",
            [],
        )
    )

    artifact_id = None

    decision = processed.artifact_decision

    print(
        "\n[OBSERVATION DECISION]"
    )
    print(
        decision.model_dump()
    )

    if (
        decision.action == ArtifactAction.STORE
        and decision.artifact is not None
    ):
        artifact = decision.artifact

        artifact_id = artifact_store.save(
            artifact_type=artifact.artifact_type,
            summary=artifact.summary,
            data=artifact.data,
        )

        artifact_ids.append(
            artifact_id
        )

    # ------------------------------------------
    # Associate artifact with execution attempt
    # ------------------------------------------

    ephemeral = state.get(
        "ephemeral_execution_state"
    )

    if (
        artifact_id is not None
        and ephemeral is not None
        and ephemeral.current_attempt_id is not None
    ):
        ExecutionMemoryManager.add_artifact(
            execution_memory=state[
                "execution_memory"
            ],
            attempt_id=ephemeral.current_attempt_id,
            artifact_id=artifact_id,
        )

    # ------------------------------------------
    # Deterministic memory update
    # ------------------------------------------

    mutate_state(
        state=state,
        proposal=processed.memory_update,
    )

    # ------------------------------------------
    # Clear execution tracking
    #
    # The artifact association must happen BEFORE
    # clearing current_attempt_id.
    # ------------------------------------------

    if ephemeral is not None:
        ephemeral.current_attempt_id = None

    return {
        "artifact_ids": artifact_ids,
        "active_memory": state[
            "active_memory"
        ],
        "execution_memory": state[
            "execution_memory"
        ],
        "ephemeral_execution_state": ephemeral,
    }