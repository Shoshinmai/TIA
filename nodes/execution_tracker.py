from agents.terminal.memory.execution_manager import (
    ExecutionMemoryManager,
)
from agents.terminal.models import (
    EphemeralExecutionState,
)
from agents.terminal.state import TerminalState


def execution_tracker_node(
    state: TerminalState,
) -> dict:
    """
    Start execution tracking for the next ExecutionWorkflow step.

    This node performs deterministic bookkeeping only.
    It does not execute the capability.
    """

    workflow = state.get(
        "execution_workflow"
    )

    if workflow is None:
        raise ValueError(
            "Cannot start execution tracking without "
            "an ExecutionWorkflow."
        )

    # ----------------------------------------------------------
    # Locate the next step that WorkflowRuntime will execute.
    # ----------------------------------------------------------

    next_step = next(
        (
            step
            for step in workflow.steps
            if step.status.value == "pending"
        ),
        None,
    )

    if next_step is None:
        raise ValueError(
            "ExecutionWorkflow has no pending step "
            "to execute."
        )

    # ----------------------------------------------------------
    # Re-entry protection
    # ----------------------------------------------------------

    ephemeral = state.get(
        "ephemeral_execution_state"
    )

    if ephemeral is None:
        ephemeral = EphemeralExecutionState()

    if ephemeral.current_attempt_id is not None:
        return {
            "ephemeral_execution_state": ephemeral,
        }

    # ----------------------------------------------------------
    # Start execution attempt
    # ----------------------------------------------------------

    attempt = ExecutionMemoryManager.start_attempt(
        execution_memory=state["execution_memory"],
        capability=next_step.capability,
        strategy=next_step.description,
        arguments=next_step.arguments,
    )

    ephemeral.current_attempt_id = attempt.attempt_id

    return {
        "execution_memory": state["execution_memory"],
        "ephemeral_execution_state": ephemeral,
    }