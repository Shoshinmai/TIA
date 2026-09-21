from __future__ import annotations

from memory import artifact_store
from memory.execution_manager import (
    ExecutionMemoryManager,
)
from models import (
    ArtifactReference,
    MemoryScope,
)
from result_processing.models import (
    ArtifactAction,
)
from result_processing.state_mutator import mutate_state
from runtime.concurrent_reconciliation import (
    ConcurrentReconciliationResult,
)
from runtime.task_execution import (
    TaskExecutionResult,
    TaskExecutionStatus,
)
from task_plan.manager import (
    TaskPlanManager,
)
from task_plan.models import (
    TaskPlan,
)


class TaskResultReconciler:
    """
    Reconcile terminal task execution results into authoritative
    central runtime state.

    This is the boundary between task-local worker execution and
    central runtime state.

    Workers never mutate:
    - TaskPlan
    - artifact_references
    - central ExecutionMemory

    They return TaskExecutionResult objects containing task-local
    processing results.

    The reconciler centrally applies:
    - task lifecycle results
    - artifact persistence
    - artifact references
    - artifact ↔ execution-attempt associations
    - dependency readiness

    For concurrent execution, reconciliation happens for the
    complete execution wave rather than for individual worker
    completion events.
    """

    @staticmethod
    def reconcile(
        *,
        plan: TaskPlan,
        results: list[TaskExecutionResult],
        state: dict,
    ) -> ConcurrentReconciliationResult:
        """
        Reconcile one completed execution wave.

        The complete result wave is applied to authoritative
        central state before dependency readiness is recomputed.

        No individual result is allowed to release dependent work
        before the entire wave has been reconciled.

        Returns a deterministic summary describing what was
        reconciled.
        """

        # ======================================================
        # Wave identity
        # ======================================================

        wave_task_ids = [
            result.task_id
            for result in results
        ]

        print(
            f"\n[RECONCILER] "
            f"Starting wave reconciliation | "
            f"plan={plan.plan_id} | "
            f"results={len(results)}"
        )

        print(
            "[RECONCILER] "
            f"Wave tasks: {wave_task_ids}"
        )

        # ------------------------------------------------------
        # Validate that all results belong to this plan.
        # ------------------------------------------------------

        for result in results:

            print(
                f"[RECONCILER] "
                f"Task result | "
                f"task={result.task_id} | "
                f"execution={result.execution_id} | "
                f"attempt={result.execution_attempt_id} | "
                f"status={result.status}"
            )

            if result.plan_id != plan.plan_id:
                raise ValueError(
                    "Cannot reconcile a result belonging to a "
                    "different plan. Expected "
                    f"'{plan.plan_id}', received "
                    f"'{result.plan_id}'."
                )

        # ------------------------------------------------------
        # Validate central artifact state.
        # ------------------------------------------------------

        artifact_references = state.get(
            "artifact_references",
        )

        if artifact_references is None:
            raise ValueError(
                "Cannot reconcile artifacts because TerminalState "
                "does not contain artifact_references."
            )

        execution_memory = state.get(
            "execution_memory",
        )

        if execution_memory is None:
            raise ValueError(
                "Cannot reconcile artifacts because TerminalState "
                "does not contain execution_memory."
            )

        # ======================================================
        # Tracking for the wave summary
        # ======================================================

        merged_attempt_ids: list[str] = []

        persisted_artifact_ids: list[str] = []

        # ======================================================
        # 1. Apply all terminal execution outcomes
        # ======================================================
        #
        # IMPORTANT:
        #
        # Readiness is intentionally NOT updated here.
        #
        # Every result in the wave must first reach its terminal
        # TaskPlan state.
        # ======================================================

        for result in results:

            print(
                f"[RECONCILER] "
                f"Applying task outcome | "
                f"task={result.task_id} | "
                f"status={result.status}"
            )

            if result.status == TaskExecutionStatus.COMPLETED:

                TaskPlanManager.complete_task(
                    plan=plan,
                    task_id=result.task_id,
                )

                continue

            if result.status == TaskExecutionStatus.FAILED:

                TaskPlanManager.fail_task(
                    plan=plan,
                    task_id=result.task_id,
                    reason=(
                        result.error
                        or "Task execution failed."
                    ),
                )

                continue

            if result.status == TaskExecutionStatus.CANCELLED:

                TaskPlanManager.cancel_task(
                    plan=plan,
                    task_id=result.task_id,
                )

                continue

            raise ValueError(
                "Cannot reconcile non-terminal task execution "
                f"status '{result.status}'."
            )

        # ======================================================
        # 2. Reconcile execution memory + artifacts
        # ======================================================
        #
        # This remains centralized.
        #
        # Each result carries its own execution_attempt_id, so
        # reconciliation never depends on completion order or
        # ExecutionMemoryManager.current_attempt().
        # ======================================================

        print(
            "[RECONCILER] "
            "Beginning artifact/memory reconciliation."
        )

        for result in results:

            reconciliation = (
                TaskResultReconciler._reconcile_artifacts(
                    result=result,
                    state=state,
                )
            )

            merged_attempt_ids.extend(
                reconciliation["merged_attempt_ids"]
            )

            persisted_artifact_ids.extend(
                reconciliation["persisted_artifact_ids"]
            )
        
        # ======================================================
        # 2B. Reconcile Active Task Memory
        # ======================================================
        #
        # RuntimeProcessingResult is intentionally pure.
        # Workers only return MemoryUpdateProposal objects.
        #
        # ActiveTaskMemory is mutated centrally after the entire
        # execution wave has been collected and reconciled.
        #
        # This preserves concurrent worker isolation while
        # allowing all task-local observations to become part of
        # the authoritative active runtime context.
        # ======================================================

        TaskResultReconciler._reconcile_active_memory(
            results=results,
            state=state,
        )

        # ======================================================
        # 3. Recompute readiness AFTER the entire wave
        # ======================================================

        print(
            "[RECONCILER] "
            "Updating task readiness after complete wave."
        )

        TaskPlanManager.update_task_readiness(
            plan=plan,
        )

        # ======================================================
        # 4. Mark tasks blocked by failed/cancelled dependencies
        # ======================================================

        blocked_tasks = (
            TaskPlanManager.get_blocked_tasks(
                plan=plan,
            )
        )

        print(
            "[RECONCILER] "
            f"Blocked tasks detected: "
            f"{[task.task_id for task in blocked_tasks]}"
        )

        for task in blocked_tasks:

            TaskPlanManager.block_task(
                plan=plan,
                task_id=task.task_id,
                blocker=(
                    "A required dependency did not complete "
                    "successfully."
                ),
            )

        # ======================================================
        # 5. Compute final READY state for the reconciled wave
        # ======================================================
        #
        # This happens after blocking as well, so the summary
        # represents the actual state that the next coordinator
        # iteration will observe.
        # ======================================================

        ready_tasks = (
            TaskPlanManager.get_ready_tasks(
                plan=plan,
            )
        )

        newly_ready_task_ids = [
            task.task_id
            for task in ready_tasks
        ]

        blocked_task_ids = [
            task.task_id
            for task in blocked_tasks
        ]

        # ======================================================
        # 6. Recompute plan terminal state
        # ======================================================

        if TaskPlanManager.is_plan_complete(
            plan=plan,
        ):
            print(
                "[RECONCILER] "
                "Plan is complete."
            )

            TaskPlanManager.complete_plan(
                plan=plan,
            )

        # ======================================================
        # 7. Build reconciliation result
        # ======================================================

        reconciliation = ConcurrentReconciliationResult(
            wave_task_ids=wave_task_ids,
            reconciled_task_ids=[
                result.task_id
                for result in results
            ],
            newly_ready_task_ids=newly_ready_task_ids,
            blocked_task_ids=blocked_task_ids,
            merged_attempt_ids=merged_attempt_ids,
            persisted_artifact_ids=persisted_artifact_ids,
        )

        print(
            "\n[RECONCILER] "
            "Wave reconciliation complete."
        )

        print(
            f"[RECONCILER] "
            f"wave={reconciliation.wave_task_ids}"
        )

        print(
            f"[RECONCILER] "
            f"reconciled="
            f"{reconciliation.reconciled_task_ids}"
        )

        print(
            f"[RECONCILER] "
            f"ready="
            f"{reconciliation.newly_ready_task_ids}"
        )

        print(
            f"[RECONCILER] "
            f"blocked="
            f"{reconciliation.blocked_task_ids}"
        )

        print(
            f"[RECONCILER] "
            f"merged_attempts="
            f"{reconciliation.merged_attempt_ids}"
        )

        print(
            f"[RECONCILER] "
            f"artifacts="
            f"{reconciliation.persisted_artifact_ids}"
        )

        return reconciliation
    
    @staticmethod
    def _reconcile_active_memory(
        *,
        results: list[TaskExecutionResult],
        state: dict,
    ) -> None:
        """
        Apply task-local MemoryUpdateProposal objects to the
        authoritative ActiveTaskMemory.

        RuntimeProcessingResult remains pure. Workers never mutate
        central ActiveTaskMemory directly.

        Every memory proposal produced during the completed
        execution wave is applied centrally in deterministic result
        order.

        The actual mutation and memory-quality validation remain
        owned by the canonical result-processing state mutator.
        """

        active_memory = state.get(
            "active_memory",
        )

        if active_memory is None:
            raise ValueError(
                "Cannot reconcile active memory because "
                "TerminalState does not contain active_memory."
            )

        print(
            "\n[ACTIVE MEMORY] "
            "Beginning wave memory reconciliation."
        )

        total_processing_results = 0
        total_memory_proposals = 0

        for result in results:

            print(
                f"[ACTIVE MEMORY] "
                f"Task={result.task_id} | "
                f"processing_results="
                f"{len(result.processing_results)}"
            )

            for index, processing_result in enumerate(
                result.processing_results
            ):
                total_processing_results += 1

                proposal = (
                    processing_result.memory_update
                )

                if proposal is None:
                    print(
                        f"[ACTIVE MEMORY] "
                        f"Task={result.task_id} | "
                        f"result={index} | "
                        "no memory proposal"
                    )

                    continue

                total_memory_proposals += 1

                print(
                    f"[ACTIVE MEMORY] "
                    f"Applying proposal | "
                    f"task={result.task_id} | "
                    f"result={index} | "
                    f"facts="
                    f"{len(proposal.known_facts)} | "
                    f"resources="
                    f"{len(proposal.discovered_resources)} | "
                    f"completed="
                    f"{len(proposal.completed_work)} | "
                    f"unresolved="
                    f"{len(proposal.unresolved_needs)}"
                )

                mutate_state(
                    state=state,
                    proposal=proposal,
                )

        print(
            "[ACTIVE MEMORY] "
            "Wave memory reconciliation complete | "
            f"processing_results="
            f"{total_processing_results} | "
            f"proposals="
            f"{total_memory_proposals} | "
            f"facts="
            f"{len(active_memory.known_facts)} | "
            f"resources="
            f"{len(active_memory.discovered_resources)} | "
            f"completed="
            f"{len(active_memory.completed_work)} | "
            f"unresolved="
            f"{len(active_memory.unresolved_needs)}"
        )

    @staticmethod
    def _reconcile_artifacts(
        *,
        result: TaskExecutionResult,
        state: dict,
    ) -> dict[str, list[str]]:
        """
        Reconcile task-local execution memory and artifacts into
        authoritative central runtime state.

        Ordering:

            1. merge the completed execution attempt
            2. persist artifact candidates
            3. associate persisted artifact IDs with that attempt

        Concurrent workers never depend on completion order.
        """

        artifact_references = state[
            "artifact_references"
        ]

        execution_memory = state[
            "execution_memory"
        ]

        merged_attempt_ids: list[str] = []

        persisted_artifact_ids: list[str] = []

        print(
            f"[ARTIFACT] "
            f"Processing task | "
            f"task={result.task_id} | "
            f"attempt={result.execution_attempt_id} | "
            f"processing_results="
            f"{len(result.processing_results)}"
        )

        # ======================================================
        # 1. Merge the worker's completed execution attempt.
        # ======================================================

        attempt = result.execution_attempt

        if attempt is not None:

            print(
                f"[MEMORY] "
                f"Merging attempt | "
                f"task={result.task_id} | "
                f"attempt={result.execution_attempt_id}"
            )

            # --------------------------------------------------
            # Defensive identity check.
            # --------------------------------------------------

            if (
                result.execution_attempt_id is not None
                and attempt.attempt_id
                != result.execution_attempt_id
            ):
                raise ValueError(
                    "TaskExecutionResult execution attempt "
                    "identity mismatch: "
                    f"result has "
                    f"'{result.execution_attempt_id}', "
                    f"but execution_attempt contains "
                    f"'{attempt.attempt_id}'."
                )

            ExecutionMemoryManager.merge_completed_attempt(
                execution_memory=execution_memory,
                attempt=attempt,
            )

            merged_attempt_ids.append(
                attempt.attempt_id
            )

            print(
                f"[MEMORY] "
                f"Attempt merged | "
                f"task={result.task_id} | "
                f"attempt={attempt.attempt_id}"
            )

        else:

            print(
                f"[MEMORY] "
                f"No execution attempt payload | "
                f"task={result.task_id} | "
                f"attempt={result.execution_attempt_id}"
            )

        # ======================================================
        # 2. Persist stored artifact candidates.
        # ======================================================

        for processing_result in (
            result.processing_results
        ):

            decision = (
                processing_result.artifact_decision
            )

            print(
                f"[ARTIFACT] "
                f"Decision | "
                f"task={result.task_id} | "
                f"attempt={result.execution_attempt_id} | "
                f"action={decision.action}"
            )

            if decision.action != ArtifactAction.STORE:

                print(
                    f"[ARTIFACT] "
                    f"Skipping persistence | "
                    f"task={result.task_id} | "
                    f"action={decision.action}"
                )

                continue

            artifact = decision.artifact

            if artifact is None:
                raise ValueError(
                    "Artifact decision requested STORE but "
                    "contained no artifact candidate."
                )

            print(
                f"[ARTIFACT] "
                f"Persisting artifact | "
                f"task={result.task_id} | "
                f"attempt={result.execution_attempt_id} | "
                f"type={artifact.artifact_type}"
            )

            # --------------------------------------------------
            # Persist artifact globally.
            # --------------------------------------------------

            artifact_id = artifact_store.save(
                artifact_type=artifact.artifact_type,
                summary=artifact.summary,
                data=artifact.data,
                metadata={
                    "plan_id": result.plan_id,
                    "task_id": result.task_id,
                    "execution_id": result.execution_id,
                },
            )

            persisted_artifact_ids.append(
                artifact_id
            )

            print(
                f"[ARTIFACT] "
                f"Artifact stored | "
                f"task={result.task_id} | "
                f"attempt={result.execution_attempt_id} | "
                f"artifact_id={artifact_id}"
            )

            # --------------------------------------------------
            # Create lightweight central reference.
            # --------------------------------------------------

            reference = ArtifactReference(
                artifact_id=artifact_id,
                artifact_type=artifact.artifact_type,
                summary=artifact.summary,
                source=(
                    processing_result
                    .normalized_result
                    .context
                    .tool_name
                ),
                scope=MemoryScope.TASK,
            )

            # --------------------------------------------------
            # Avoid duplicate references.
            # --------------------------------------------------

            already_present = any(
                existing.artifact_id
                == reference.artifact_id
                for existing
                in artifact_references
            )

            if not already_present:

                artifact_references.append(
                    reference
                )

                print(
                    f"[ARTIFACT] "
                    f"Reference registered | "
                    f"task={result.task_id} | "
                    f"artifact_id={artifact_id}"
                )

            else:

                print(
                    f"[ARTIFACT] "
                    f"Reference already present | "
                    f"task={result.task_id} | "
                    f"artifact_id={artifact_id}"
                )

            # ==================================================
            # 3. Associate artifact with exact attempt.
            # ==================================================

            print(
                f"[MEMORY] "
                f"Associating artifact | "
                f"task={result.task_id} | "
                f"attempt={result.execution_attempt_id} | "
                f"artifact={artifact_id}"
            )

            TaskResultReconciler._associate_artifact_with_attempt(
                result=result,
                artifact_id=artifact_id,
                execution_memory=execution_memory,
            )

            print(
                f"[MEMORY] "
                f"Artifact associated | "
                f"task={result.task_id} | "
                f"attempt={result.execution_attempt_id} | "
                f"artifact={artifact_id}"
            )

        return {
            "merged_attempt_ids": merged_attempt_ids,
            "persisted_artifact_ids": persisted_artifact_ids,
        }

    @staticmethod
    def _associate_artifact_with_attempt(
        *,
        result: TaskExecutionResult,
        artifact_id: str,
        execution_memory,
    ) -> None:
        """
        Associate an artifact with the exact execution attempt
        that produced the task result.

        Concurrent workers must never rely on
        ExecutionMemoryManager.current_attempt() here because
        multiple workers may complete in arbitrary order.

        The TaskExecutionResult therefore carries the explicit
        execution_attempt_id created by the TaskWorker.
        """

        attempt_id = result.execution_attempt_id

        if not attempt_id:
            raise ValueError(
                "Cannot associate artifact with ExecutionMemory: "
                f"task '{result.task_id}' returned an artifact "
                "without an execution_attempt_id."
            )

        ExecutionMemoryManager.add_artifact(
            execution_memory=execution_memory,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
        )