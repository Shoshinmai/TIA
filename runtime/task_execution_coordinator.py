from __future__ import annotations

from dataclasses import dataclass, field

from runtime.concurrent_task_executor import (
    ConcurrentTaskExecutor,
)
from runtime.task_execution import (
    TaskExecutionResult,
)
from runtime.task_result_reconciler import (
    TaskResultReconciler,
)
from task_plan.manager import TaskPlanManager
from task_plan.models import TaskPlan


@dataclass
class CoordinatedPlanExecution:
    """
    Terminal result of one concurrent execution wave.

    The coordinator owns exactly one execution boundary:

        READY discovery
            ↓
        wave admission
            ↓
        concurrent execution
            ↓
        central reconciliation
            ↓
        return to Runtime

    The Runtime/Critic layer decides whether another wave should
    be executed.

    This object therefore contains only the results produced by
    the current wave.
    """

    plan: TaskPlan

    task_results: list[TaskExecutionResult] = field(
        default_factory=list,
    )


class TaskExecutionCoordinator:
    """
    Orchestrate exactly one dependency-aware concurrent execution wave.

    Responsibilities:
    - discover the current READY tasks
    - admit one execution wave
    - run that wave concurrently
    - reconcile that wave centrally
    - return the authoritative plan state

    This component owns orchestration only.

    It does NOT:
    - execute individual tasks
    - reason about task objectives
    - perform LLM calls
    - make Critic decisions
    - automatically execute a newly-ready dependent wave

    IMPORTANT:

    A newly-ready wave is intentionally returned to the Runtime
    rather than executed immediately.

    This creates the required boundary:

        wave N
          ↓
        reconcile
          ↓
        Critic
          ↓
        Runtime decision
          ↓
        wave N+1
    """

    def __init__(
        self,
        *,
        executor: ConcurrentTaskExecutor,
    ) -> None:
        self.executor = executor

    async def execute_plan(
        self,
        *,
        plan: TaskPlan,
        state: dict,
    ) -> CoordinatedPlanExecution:
        """
        Execute exactly ONE currently-admitted concurrent wave.

        This method intentionally does NOT loop until the complete
        TaskPlan is exhausted.

        The lifecycle is:

            1. update READY state
            2. discover READY tasks
            3. admit those tasks
            4. execute them concurrently
            5. reconcile the wave
            6. return

        After reconciliation, newly-ready dependent tasks are left
        READY for the Runtime/Critic cycle to evaluate.

        Returns:
            The authoritative TaskPlan after this wave and the
            terminal results produced by this wave.
        """

        # ------------------------------------------------------
        # Establish current readiness.
        # ------------------------------------------------------

        TaskPlanManager.update_task_readiness(
            plan=plan,
        )

        # ------------------------------------------------------
        # Plan already complete.
        #
        # There is no wave to execute. Returning immediately lets
        # the caller build a plan-level review outcome and invoke
        # the Critic.
        # ------------------------------------------------------

        if TaskPlanManager.is_plan_complete(
            plan=plan,
        ):
            print(
                "\n[COORDINATOR] "
                "Plan is already complete. "
                "No execution wave required."
            )

            return CoordinatedPlanExecution(
                plan=plan,
                task_results=[],
            )

        # ------------------------------------------------------
        # Select the CURRENT READY wave only.
        # ------------------------------------------------------

        ready_tasks = (
            TaskPlanManager.get_ready_tasks(
                plan=plan,
            )
        )

        print(
            "\n[COORDINATOR] "
            f"READY tasks: "
            f"{[task.task_id for task in ready_tasks]}"
        )

        # ------------------------------------------------------
        # No READY work.
        #
        # Do not attempt another scheduling pass here.
        # The Runtime/Critic boundary should inspect the stable
        # plan state and decide what happens next.
        # ------------------------------------------------------

        if not ready_tasks:

            print(
                "[COORDINATOR] "
                "No READY tasks remain. "
                "Returning control to Runtime."
            )

            return CoordinatedPlanExecution(
                plan=plan,
                task_results=[],
            )

        # ------------------------------------------------------
        # Admit the current READY wave.
        #
        # READY → IN_PROGRESS happens exactly once for this wave.
        # ------------------------------------------------------

        execution_wave = (
            TaskPlanManager.start_ready_tasks(
                plan=plan,
                limit=len(ready_tasks),
            )
        )

        if not execution_wave:

            print(
                "[COORDINATOR] "
                "No tasks were admitted into the wave. "
                "Returning control to Runtime."
            )

            return CoordinatedPlanExecution(
                plan=plan,
                task_results=[],
            )

        print(
            "\n[COORDINATOR] "
            "Starting execution wave | "
            f"tasks="
            f"{[task.task_id for task in execution_wave]}"
        )

        # ------------------------------------------------------
        # Execute ONLY this wave concurrently.
        # ------------------------------------------------------

        results = await self.executor.execute(
            plan_id=plan.plan_id,
            tasks=execution_wave,
            state=state,
        )

        print(
            "\n[COORDINATOR] "
            "Wave execution complete | "
            f"results="
            f"{[result.task_id for result in results]}"
        )

        # ------------------------------------------------------
        # Reconcile this complete wave before returning.
        #
        # This updates:
        # - task status
        # - execution memory
        # - active memory
        # - artifacts
        # - dependency readiness
        #
        # Newly-ready tasks are deliberately NOT executed here.
        # ------------------------------------------------------

        reconciliation = (
            TaskResultReconciler.reconcile(
                plan=plan,
                results=results,
                state=state,
            )
        )

        print(
            "\n[COORDINATOR] "
            "Wave reconciliation complete."
        )

        print(
            "[COORDINATOR] "
            f"Reconciled: "
            f"{reconciliation.reconciled_task_ids}"
        )

        print(
            "[COORDINATOR] "
            f"New READY: "
            f"{reconciliation.newly_ready_task_ids}"
        )

        print(
            "[COORDINATOR] "
            f"Blocked: "
            f"{reconciliation.blocked_task_ids}"
        )

        print(
            "[COORDINATOR] "
            f"Merged attempts: "
            f"{reconciliation.merged_attempt_ids}"
        )

        print(
            "[COORDINATOR] "
            f"Persisted artifacts: "
            f"{reconciliation.persisted_artifact_ids}"
        )

        # ------------------------------------------------------
        # CRITICAL BOUNDARY
        #
        # Do NOT loop back into TaskPlanManager here.
        #
        # The current wave has finished and the resulting plan
        # state is now stable enough for the Critic to inspect.
        # ------------------------------------------------------

        print(
            "\n[COORDINATOR] "
            "Wave boundary reached. "
            "Returning control to Runtime/Critic."
        )

        return CoordinatedPlanExecution(
            plan=plan,
            task_results=results,
        )