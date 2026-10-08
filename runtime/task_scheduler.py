from __future__ import annotations

from runtime.task_execution import (
    TaskExecutionContext,
    TaskExecutionStatus,
)
from task_executor.models import ExecutionWorkflow
from task_plan.manager import TaskPlanManager
from task_plan.models import (
    TaskPlan,
)


class TaskScheduler:
    """
    Deterministic owner of active task execution contexts.

    Responsibilities:
    - resolve task readiness
    - enforce bounded task concurrency
    - admit READY tasks for execution
    - create isolated TaskExecutionContexts
    - track active executions
    - attach workflows to the correct task execution
    - release completed/failed/cancelled executions

    This class performs no LLM reasoning and does not execute tools.

    TaskPlanManager remains the sole owner of TaskPlan lifecycle
    mutation.
    """

    def __init__(
        self,
        *,
        max_concurrent_tasks: int = 3,
    ) -> None:

        if max_concurrent_tasks < 1:
            raise ValueError(
                "max_concurrent_tasks must be at least 1."
            )

        self.max_concurrent_tasks = max_concurrent_tasks

        self._active_executions: dict[
            str,
            TaskExecutionContext,
        ] = {}

        self._admission_paused = False

    # --------------------------------------------------------------
    # Queries
    # --------------------------------------------------------------

    def get_active_executions(
        self,
    ) -> list[TaskExecutionContext]:
        """
        Return all active task execution contexts.
        """

        return list(self._active_executions.values())

    def get_execution(
        self,
        *,
        task_id: str,
    ) -> TaskExecutionContext | None:
        """
        Return the active execution context for a task.
        """

        return self._active_executions.get(task_id)

    @property
    def active_count(self) -> int:
        """
        Number of tasks currently admitted for execution.
        """

        return len(self._active_executions)

    @property
    def available_capacity(self) -> int:
        """
        Number of additional tasks that may be admitted.
        """

        return max(
            0,
            self.max_concurrent_tasks - self.active_count,
        )

    @property
    def admission_paused(self) -> bool:
        """
        Whether the scheduler is temporarily admitting no new work.
        """

        return self._admission_paused

    # --------------------------------------------------------------
    # Admission Control
    # --------------------------------------------------------------

    def pause_admission(self) -> None:
        """
        Stop admitting new tasks.

        Existing active executions remain untouched.

        This provides the foundation for future replanning barriers.
        """

        self._admission_paused = True

    def resume_admission(self) -> None:
        """
        Resume normal task admission.
        """

        self._admission_paused = False

    def admit_ready_tasks(
        self,
        *,
        plan: TaskPlan,
    ) -> list[TaskExecutionContext]:
        """
        Admit READY tasks up to available concurrency capacity.

        Admission performs:

            PENDING
               ↓
        dependency resolution
               ↓
            READY
               ↓
        scheduler admission
               ↓
         IN_PROGRESS
               ↓
        TaskExecutionContext

        No actual asynchronous execution occurs here yet.
        """

        if self._admission_paused:
            return []

        # Resolve newly unblocked tasks first.
        TaskPlanManager.update_task_readiness(
            plan=plan,
        )

        capacity = self.available_capacity

        if capacity == 0:
            return []

        started_tasks = TaskPlanManager.start_ready_tasks(
            plan=plan,
            limit=capacity,
        )

        contexts: list[TaskExecutionContext] = []

        for task in started_tasks:

            if task.task_id in self._active_executions:
                raise RuntimeError(
                    f"Task '{task.task_id}' already has an active "
                    "execution context."
                )

            context = TaskExecutionContext(
                plan_id=plan.plan_id,
                task_id=task.task_id,
                status=TaskExecutionStatus.CREATED,
            )

            self._active_executions[task.task_id] = context
            contexts.append(context)

        return contexts

    # --------------------------------------------------------------
    # Execution Lifecycle
    # --------------------------------------------------------------

    def start_execution(
        self,
        *,
        task_id: str,
    ) -> TaskExecutionContext:
        """
        Mark an admitted execution context as running.
        """

        context = self._require_execution(
            task_id=task_id,
        )

        if context.status != TaskExecutionStatus.CREATED:
            raise ValueError(
                f"Task '{task_id}' cannot start execution because "
                f"its execution status is '{context.status}'."
            )

        context.status = TaskExecutionStatus.RUNNING

        return context

    def attach_workflow(
        self,
        *,
        task_id: str,
        workflow: ExecutionWorkflow,
    ) -> TaskExecutionContext:
        """
        Attach a workflow to its owning task execution.

        Concurrent execution requires explicit workflow ownership.
        """

        context = self._require_execution(
            task_id=task_id,
        )

        if workflow.task_id is None:
            workflow.task_id = task_id

        if workflow.task_id != task_id:
            raise ValueError(
                f"Workflow '{workflow.workflow_id}' belongs to "
                f"task '{workflow.task_id}', not task '{task_id}'."
            )

        context.workflow = workflow

        return context

    def set_active_attempt(
        self,
        *,
        task_id: str,
        attempt_id: str,
    ) -> None:
        """
        Associate the current ExecutionMemory attempt with one
        task-scoped execution context.
        """

        context = self._require_execution(
            task_id=task_id,
        )

        context.active_attempt_id = attempt_id

    def clear_active_attempt(
        self,
        *,
        task_id: str,
    ) -> None:
        """
        Clear the active attempt pointer for a task.
        """

        context = self._require_execution(
            task_id=task_id,
        )

        context.active_attempt_id = None

    # --------------------------------------------------------------
    # Completion / Failure
    # --------------------------------------------------------------

    def complete_execution(
        self,
        *,
        plan: TaskPlan,
        task_id: str,
        result: dict | None = None,
    ) -> TaskExecutionContext:
        """
        Complete a task execution and release scheduler capacity.

        TaskPlan lifecycle mutation remains delegated to
        TaskPlanManager.
        """

        context = self._require_execution(
            task_id=task_id,
        )

        TaskPlanManager.complete_task(
            plan=plan,
            task_id=task_id,
        )

        context.status = TaskExecutionStatus.COMPLETED
        context.result = result
        context.active_attempt_id = None

        del self._active_executions[task_id]

        return context

    def fail_execution(
        self,
        *,
        plan: TaskPlan,
        task_id: str,
        reason: str,
    ) -> TaskExecutionContext:
        """
        Fail a task execution and release scheduler capacity.
        """

        context = self._require_execution(
            task_id=task_id,
        )

        TaskPlanManager.fail_task(
            plan=plan,
            task_id=task_id,
            reason=reason,
        )

        context.status = TaskExecutionStatus.FAILED
        context.error = reason
        context.active_attempt_id = None

        del self._active_executions[task_id]

        return context

    def cancel_execution(
        self,
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> TaskExecutionContext:
        """
        Cancel an active task execution and release scheduler capacity.
        """

        context = self._require_execution(
            task_id=task_id,
        )

        TaskPlanManager.cancel_task(
            plan=plan,
            task_id=task_id,
        )

        context.status = TaskExecutionStatus.CANCELLED
        context.active_attempt_id = None

        del self._active_executions[task_id]

        return context

    # --------------------------------------------------------------
    # Internal Helpers
    # --------------------------------------------------------------

    def _require_execution(
        self,
        *,
        task_id: str,
    ) -> TaskExecutionContext:

        context = self._active_executions.get(task_id)

        if context is None:
            raise ValueError(
                f"Task '{task_id}' has no active execution context."
            )

        return context