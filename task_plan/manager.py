from __future__ import annotations

from uuid import uuid4
from agents.terminal.task_plan.models import (
    TaskItemStatus,
    TaskPlanStatus,
    TaskPlan,
    TaskItem,
)


class TaskPlanManager:
    """
    Deterministic owner of TaskPlan state.

    This class is the only component allowed to mutate a TaskPlan.
    It performs no reasoning and contains no LLM logic.
    """

    from uuid import uuid4

    # ------------------------------------------------------------------
    # Plan Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def create_plan(
        *,
        goal: str,
        tasks: list[TaskItem],
    ) -> TaskPlan:
        """
        Create a new task plan.

        This method only constructs the TaskPlan.
        It does not perform validation or determine execution order.
        """

        return TaskPlan(
            plan_id=str(uuid4()),
            goal=goal,
            status=TaskPlanStatus.CREATED,
            tasks=list(tasks),
        )

    @staticmethod
    def complete_plan(
        *,
        plan: TaskPlan,
    ) -> None:
        """
        Mark the task plan as completed.
        """

        plan.status = TaskPlanStatus.COMPLETED

    @staticmethod
    def fail_plan(
        *,
        plan: TaskPlan,
        reason: str | None = None,
    ) -> None:
        """
        Mark the task plan as failed.

        The failure reason is intentionally unused for now.
        It remains in the API for future plan diagnostics.
        """

        _ = reason

        plan.status = TaskPlanStatus.FAILED

    @staticmethod
    def cancel_plan(
        *,
        plan: TaskPlan,
    ) -> None:
        """
        Cancel the task plan.
        """

        plan.status = TaskPlanStatus.CANCELLED

    # ------------------------------------------------------------------
    # Task Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def add_task(
        *,
        plan: TaskPlan,
        task: TaskItem,
    ) -> None:
        """
        Append a task to the end of the current plan.
        """

        plan.tasks.append(task)

    @staticmethod
    def insert_tasks(
        *,
        plan: TaskPlan,
        after_task_id: str | None,
        tasks: list[TaskItem],
    ) -> None:
        """
        Insert tasks into the plan.

        If after_task_id is None, insert at the beginning.
        """

        if after_task_id is None:
            plan.tasks[0:0] = tasks
            return

        for index, existing_task in enumerate(plan.tasks):
            if existing_task.task_id == after_task_id:
                plan.tasks[index + 1 : index + 1] = tasks
                return

        raise ValueError(f"Task '{after_task_id}' does not exist.")

    @staticmethod
    def remove_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> None:
        """
        Remove a task from the plan.
        """

        for index, task in enumerate(plan.tasks):
            if task.task_id == task_id:
                del plan.tasks[index]
                return

        raise ValueError(f"Task '{task_id}' does not exist.")

    @staticmethod
    def start_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> None:
        """
        Start a task that is READY for execution.

        Task lifecycle ownership remains inside TaskPlanManager.
        Only READY tasks may become IN_PROGRESS.
        """

        task = TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

        if task.status != TaskItemStatus.READY:
            raise ValueError(
                f"Task '{task_id}' cannot be started because its "
                f"current status is '{task.status}'. "
                "Only READY tasks may become IN_PROGRESS."
            )

        task.status = TaskItemStatus.IN_PROGRESS
        
    @staticmethod
    def retry_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> None:
        """
        Reset an IN_PROGRESS task so that it can be executed again.

        RETRY_TASK means the objective remains valid, but the previous
        execution workflow is no longer reusable.

        Lifecycle:

            IN_PROGRESS
                ↓
            READY
                ↓
            new ExecutionWorkflow
        """

        task = TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

        if task.status != TaskItemStatus.IN_PROGRESS:
            raise ValueError(
                f"Task '{task_id}' cannot be retried because its "
                f"current status is '{task.status}'. "
                "Only IN_PROGRESS tasks may be retried."
            )

        task.status = TaskItemStatus.READY

    @staticmethod
    def complete_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> None:
        """
        Complete the currently executing task.

        Only an IN_PROGRESS task may become COMPLETED.
        """

        task = TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

        if task.status != TaskItemStatus.IN_PROGRESS:
            raise ValueError(
                f"Task '{task_id}' cannot be completed because its "
                f"current status is '{task.status}'. "
                "Only IN_PROGRESS tasks may become COMPLETED."
            )

        task.status = TaskItemStatus.COMPLETED

    @staticmethod
    def block_task(
        *,
        plan: TaskPlan,
        task_id: str,
        blocker: str,
    ) -> None:
        """
        Mark a task as blocked.
        """

        task = TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

        task.status = TaskItemStatus.BLOCKED

        if blocker not in task.blockers:
            task.blockers.append(blocker)

    @staticmethod
    def fail_task(
        *,
        plan: TaskPlan,
        task_id: str,
        reason: str,
    ) -> None:
        """
        Mark a task as failed.
        """

        task = TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

        task.status = TaskItemStatus.FAILED

        if reason not in task.blockers:
            task.blockers.append(reason)

    @staticmethod
    def cancel_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> None:
        """
        Mark a task as cancelled.
        """

        task = TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

        task.status = TaskItemStatus.CANCELLED

    # ------------------------------------------------------------------
    # Rolling Plan
    # ------------------------------------------------------------------

    @staticmethod
    def get_current_task(
        task_plan: TaskPlan,
    ) -> TaskItem | None:
        """
        Return the next executable task in the Task Plan.

        A task is executable when:
        - it is PENDING
        - all dependencies are COMPLETED

        Returns None if no executable task exists.
        """
        for task in task_plan.tasks:

            if task.status not in (
                TaskItemStatus.PENDING,
                TaskItemStatus.READY,
            ):
                continue

            if TaskPlanManager._dependencies_completed(
                task_plan,
                task,
            ):
                return task

        return None

    @staticmethod
    def get_ready_tasks(
        *,
        plan: TaskPlan,
    ) -> list[TaskItem]:
        """
        Return all tasks that are ready for execution.

        Tasks are returned in planner-defined order.
        """

        return [task for task in plan.tasks if task.status == TaskItemStatus.READY]

    @staticmethod
    def update_task_readiness(
        *,
        plan: TaskPlan,
    ) -> None:
        """
        Update task readiness based on dependency completion.

        Any PENDING task whose dependencies have all completed becomes READY.
        """

        completed_tasks = TaskPlanManager._completed_task_ids(plan)

        for task in plan.tasks:

            if task.status != TaskItemStatus.PENDING:
                continue

            if all(dependency in completed_tasks for dependency in task.dependencies):
                task.status = TaskItemStatus.READY

    @staticmethod
    def append_tasks(
        *,
        plan: TaskPlan,
        tasks: list[TaskItem],
    ) -> None:
        """
        Append new tasks to the end of the current task plan.

        This is primarily used when the planner expands the
        rolling task plan during execution.
        """

        plan.tasks.extend(tasks)

    @staticmethod
    def replace_remaining_tasks(
        *,
        plan: TaskPlan,
        tasks: list[TaskItem],
    ) -> None:
        """
        Replace all incomplete tasks with a new set of tasks.

        Completed tasks are preserved to maintain execution history.
        This is primarily used after a replanning operation.
        """

        completed_tasks = [
            task for task in plan.tasks if task.status == TaskItemStatus.COMPLETED
        ]

        plan.tasks = completed_tasks + list(tasks)
        
    @staticmethod
    def update_remaining_tasks(
        *,
        plan: TaskPlan,
        tasks: list[TaskItem],
    ) -> None:
        """
        Replace the unfinished portion of the rolling TaskPlan.

        Completed tasks are immutable execution history and are preserved.

        All unfinished tasks from the previous plan are discarded. This
        includes the previous IN_PROGRESS task because PLAN_UPDATE_REQUIRED
        means the previous unfinished execution strategy must be reconsidered.

        Planner-generated tasks are treated only as proposed future work.
        They are therefore normalized to PENDING before dependency readiness
        is evaluated.

        The TaskPlanManager, not the Planner, owns task lifecycle state.
        """

        # --------------------------------------------------------------
        # Preserve immutable execution history.
        # --------------------------------------------------------------

        completed_tasks = [
            task
            for task in plan.tasks
            if task.status == TaskItemStatus.COMPLETED
        ]

        # --------------------------------------------------------------
        # Planner output represents proposed future work.
        #
        # The Planner must never be allowed to directly establish
        # IN_PROGRESS state.
        # --------------------------------------------------------------

        replacement_tasks: list[TaskItem] = []

        for task in tasks:

            if task.status == TaskItemStatus.COMPLETED:
                raise ValueError(
                    "Planner-generated replacement tasks cannot be "
                    "marked COMPLETED."
                )

            task.status = TaskItemStatus.PENDING

            replacement_tasks.append(task)

        # --------------------------------------------------------------
        # Replace the unfinished portion.
        # --------------------------------------------------------------

        plan.tasks = completed_tasks + replacement_tasks

        # --------------------------------------------------------------
        # Resolve which replacement tasks are immediately executable.
        # --------------------------------------------------------------

        TaskPlanManager.update_task_readiness(
            plan=plan,
        )
        
    @staticmethod
    def get_in_progress_task(
        *,
        plan: TaskPlan,
    ) -> TaskItem | None:
        """
        Return the task currently being executed.

        Returns None if no task is currently in progress.
        """

        for task in plan.tasks:
            if task.status == TaskItemStatus.IN_PROGRESS:
                return task

        return None
    
    @staticmethod
    def is_plan_complete(
        *,
        plan: TaskPlan,
    ) -> bool:
        """
        Return True when every task in the TaskPlan is completed.

        This method only evaluates deterministic TaskPlan state.
        It does not make any semantic judgement about whether the
        user's overall goal has been achieved.
        """

        if not plan.tasks:
            return False

        return all(
            task.status == TaskItemStatus.COMPLETED
            for task in plan.tasks
        )
        
    @staticmethod
    def has_remaining_tasks(
        *,
        plan: TaskPlan,
    ) -> bool:
        """
        Return True when the plan contains tasks that are not yet
        completed.

        This is a deterministic TaskPlan query.
        """

        return any(
            task.status != TaskItemStatus.COMPLETED
            for task in plan.tasks
        )
        
    @staticmethod
    def get_blocked_tasks(
        *,
        plan: TaskPlan,
    ) -> list[TaskItem]:
        """
        Return tasks that cannot currently execute because at least
        one dependency has reached a terminal non-success state.

        This method only observes TaskPlan state. It does not mutate
        tasks or decide how the blockage should be resolved.
        """

        terminal_blocking_statuses = {
            TaskItemStatus.BLOCKED,
            TaskItemStatus.FAILED,
            TaskItemStatus.CANCELLED,
        }

        status_by_id = {
            task.task_id: task.status
            for task in plan.tasks
        }

        blocked_tasks: list[TaskItem] = []

        for task in plan.tasks:

            if task.status not in (
                TaskItemStatus.PENDING,
                TaskItemStatus.READY,
            ):
                continue

            if any(
                status_by_id.get(dependency)
                in terminal_blocking_statuses
                for dependency in task.dependencies
            ):
                blocked_tasks.append(task)

        return blocked_tasks

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> TaskItem:
        """
        Return the task with the given ID.

        Raises:
            ValueError: If the task does not exist.
        """

        for task in plan.tasks:
            if task.task_id == task_id:
                return task

        raise ValueError(f"Task '{task_id}' does not exist.")

    @staticmethod
    def _completed_task_ids(
        plan: TaskPlan,
    ) -> set[str]:

        return {
            task.task_id
            for task in plan.tasks
            if task.status == TaskItemStatus.COMPLETED
        }

    @staticmethod
    def _dependencies_completed(
        plan: TaskPlan,
        task: TaskItem,
    ) -> bool:
        """
        Return True when all dependencies of the given task
        have been completed.

        A task with no dependencies is immediately executable.
        """

        if not task.dependencies:
            return True

        completed_tasks = TaskPlanManager._completed_task_ids(
            plan,
        )

        return all(dependency in completed_tasks for dependency in task.dependencies)
