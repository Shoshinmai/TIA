from __future__ import annotations

from datetime import datetime, timezone

from models import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionMemory,
)
from result_processing.models import (
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
        runtime_result: RuntimeProcessingResult | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        """
        Finalize one RUNNING execution attempt.

        A RuntimeProcessingResult is normally available after at
        least one tool result has been processed.

        A task may also fail or be cancelled before the first
        processed tool result exists. In that case the attempt
        can still be finalized using the explicit success/error
        lifecycle information.
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

        # ------------------------------------------------------
        # Final status
        # ------------------------------------------------------

        attempt.status = (
            AttemptStatus.SUCCEEDED
            if success
            else AttemptStatus.FAILED
        )

        attempt.completed_at = datetime.now(
            timezone.utc
        )

        # ------------------------------------------------------
        # Result-backed completion
        # ------------------------------------------------------

        if runtime_result is not None:

            execution = (
                runtime_result
                .normalized_result
                .execution
            )

            attempt.outcome = execution

            attempt.progress_made = bool(
                execution.progress_made
            )

            if error is not None:
                attempt.error = error
            else:
                attempt.error = (
                    execution.stderr
                    or None
                )

            return

        # ------------------------------------------------------
        # Failure/cancellation before result processing
        # ------------------------------------------------------

        attempt.outcome = (
            error
            if error is not None
            else (
                "Execution terminated before a "
                "RuntimeProcessingResult was produced."
            )
        )

        attempt.progress_made = False

        attempt.error = error

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

    @staticmethod
    def merge_completed_attempt(
        *,
        execution_memory: ExecutionMemory,
        attempt: ExecutionAttempt,
    ) -> None:
        """
        Merge one completed task-local execution attempt into
        authoritative ExecutionMemory.
        
        This operation is used by the concurrent result
        reconciliation boundary.

        The attempt was created and finalized inside an isolated
        TaskWorker ExecutionMemory. The reconciler transfers the
        completed record into central ExecutionMemory only after
        the worker has finished.

        The method never merges a RUNNING/PENDING attempt.
        """

        if attempt.status not in (
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
        ):
            raise ValueError(
                f"Cannot merge execution attempt "
                f"'{attempt.attempt_id}' because its status "
                f"is '{attempt.status.value}'. Only completed "
                "attempts may be merged."
            )

        # ------------------------------------------------------
        # Idempotent merge.
        # ------------------------------------------------------

        for existing in execution_memory.attempts:

            if existing.attempt_id == attempt.attempt_id:
                return

        execution_memory.attempts.append(
            attempt.model_copy(
                deep=True
            )
        )