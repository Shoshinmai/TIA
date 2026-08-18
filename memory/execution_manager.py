from __future__ import annotations

from datetime import datetime, timezone

from agents.terminal.models import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionMemory,
)
from agents.terminal.result_processing.models import (
    RuntimeProcessingResult,
)


class ExecutionMemoryManager:
    """
    Deterministic owner of ExecutionMemory.

    All creation and lifecycle updates of ExecutionAttempt
    records must go through this manager.
    """

    @staticmethod
    def start_attempt(
        *,
        execution_memory: ExecutionMemory,
        capability: str,
        strategy: str,
        arguments: dict,
    ) -> ExecutionAttempt:
        """
        Create a new execution attempt.
        """

        attempt = ExecutionAttempt(
            step=len(execution_memory.attempts) + 1,
            capability=capability,
            strategy=strategy,
            arguments=arguments,
            status=AttemptStatus.RUNNING,
        )

        execution_memory.attempts.append(
            attempt
        )

        return attempt

    @staticmethod
    def current_attempt(
        execution_memory: ExecutionMemory,
    ) -> ExecutionAttempt | None:
        """
        Return the most recent execution attempt.
        """

        if not execution_memory.attempts:
            return None

        return execution_memory.attempts[-1]

    @staticmethod
    def _find_attempt(
        *,
        execution_memory: ExecutionMemory,
        attempt_id: str,
    ) -> ExecutionAttempt:
        """
        Locate an execution attempt by identifier.
        """

        for attempt in execution_memory.attempts:
            if attempt.attempt_id == attempt_id:
                return attempt

        raise ValueError(
            f"Execution attempt '{attempt_id}' not found."
        )

    @staticmethod
    def finish_attempt(
        *,
        execution_memory: ExecutionMemory,
        attempt_id: str,
        runtime_result: RuntimeProcessingResult,
        success: bool,
        error: str | None = None,
    ) -> None:
        """
        Finalize one RUNNING execution attempt.
        """

        attempt = ExecutionMemoryManager._find_attempt(
            execution_memory=execution_memory,
            attempt_id=attempt_id,
        )

        # ------------------------------------------------------
        # Execution lifecycle invariant
        # ------------------------------------------------------

        if attempt.status != AttemptStatus.RUNNING:
            raise ValueError(
                f"Execution attempt '{attempt_id}' "
                f"cannot be finished because its current "
                f"status is '{attempt.status.value}'."
            )

        execution = (
            runtime_result
            .normalized_result
            .execution
        )

        attempt.status = (
            AttemptStatus.SUCCEEDED
            if success
            else AttemptStatus.FAILED
        )

        attempt.completed_at = datetime.now(
            timezone.utc
        )

        attempt.outcome = execution

        attempt.progress_made = bool(
            execution.progress_made
        )

        attempt.error = (
            error
            if error is not None
            else execution.stderr or None
        )

    @staticmethod
    def add_artifact(
        *,
        execution_memory: ExecutionMemory,
        attempt_id: str,
        artifact_id: str,
    ) -> None:
        """
        Associate an artifact with an execution attempt.
        """

        attempt = ExecutionMemoryManager._find_attempt(
            execution_memory=execution_memory,
            attempt_id=attempt_id,
        )

        if artifact_id not in attempt.artifact_ids:
            attempt.artifact_ids.append(
                artifact_id
            )