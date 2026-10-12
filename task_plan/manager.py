from __future__ import annotations

from uuid import uuid4
from task_plan.models import (
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

        Increments attempt_count on READY → IN_PROGRESS.
        Blocks if attempt_count >= max_attempts.
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

        # Check attempt budget before starting
        if task.attempt_count >= task.max_attempts:
            raise ValueError(
                f"Task '{task_id}' has exhausted its attempt budget "
                f"({task.attempt_count}/{task.max_attempts}). "
                "Cannot start further executions."
            )

        task.status = TaskItemStatus.IN_PROGRESS
        task.attempt_count += 1

    @staticmethod
    def find_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> TaskItem | None:
        """
        Return the task with the given ID, or None.

        Used for admission checks against model-supplied IDs,
        where an unknown ID must not raise.
        """

        for task in plan.tasks:
            if task.task_id == task_id:
                return task

        return None

    @staticmethod
    def get_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> TaskItem:
        """
        Return a specific task by ID.

        This is a read-only public lookup used by runtime components.
        """
        return TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

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

        Does NOT increment attempt_count. The count increments on
        the next start_task/start_ready_tasks call.
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

        # Check attempt budget (will be enforced on next start)
        if task.attempt_count >= task.max_attempts:
            raise ValueError(
                f"Task '{task_id}' has exhausted its attempt budget "
                f"({task.attempt_count}/{task.max_attempts}). "
                "Cannot retry further."
            )

        task.status = TaskItemStatus.READY
        task.confirmed = False
        task.evidence.clear()
        # attempt_count NOT incremented here; increments on next start

    @staticmethod
    def retry_failed_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> None:
        """
        Requeue a FAILED task for another execution attempt.

        This is the concurrent-review recovery path.

        Lifecycle:

            FAILED
                ↓
            READY
                ↓
            new execution wave

        Does NOT increment attempt_count. The count increments on
        the next start_task/start_ready_tasks call.
        """

        task = TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

        if task.status != TaskItemStatus.FAILED:
            raise ValueError(
                f"Task '{task_id}' cannot be retried because its "
                f"current status is '{task.status}'. "
                "Only FAILED tasks may enter concurrent retry."
            )

        # Check attempt budget (will be enforced on next start)
        if task.attempt_count >= task.max_attempts:
            raise ValueError(
                f"Task '{task_id}' has exhausted its attempt budget "
                f"({task.attempt_count}/{task.max_attempts}). "
                "Cannot retry further."
            )

        task.status = TaskItemStatus.READY
        task.confirmed = False
        task.evidence.clear()
        task.blockers.clear()
        # attempt_count NOT incremented here; increments on next start

    @staticmethod
    def retry_completed_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> None:
        """
        Requeue a completed task when the Critic determines that
        the latest execution did not actually satisfy the objective.

        Lifecycle:

            COMPLETED
                ↓
            READY
                ↓
            new execution wave

        Does NOT increment attempt_count. The count increments on
        the next start_task/start_ready_tasks call.
        """

        task = TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

        if task.status != TaskItemStatus.COMPLETED:
            raise ValueError(
                f"Task '{task_id}' cannot be retried because its "
                f"current status is '{task.status}'. "
                "Only COMPLETED tasks may enter completed retry."
            )

        # Check attempt budget (will be enforced on next start)
        if task.attempt_count >= task.max_attempts:
            raise ValueError(
                f"Task '{task_id}' has exhausted its attempt budget "
                f"({task.attempt_count}/{task.max_attempts}). "
                "Cannot retry further."
            )

        task.status = TaskItemStatus.READY
        task.confirmed = False
        task.evidence.clear()
        # attempt_count NOT incremented here; increments on next start

    @staticmethod
    def confirm_task(
        *,
        plan: TaskPlan,
        task_id: str,
    ) -> None:
        """
        Record Critic confirmation that a completed task's success
        criteria are satisfied.

        Only the Critic's TASK_COMPLETED decision may confirm a task.
        Execution completing workflow steps is never sufficient.
        """

        task = TaskPlanManager._find_task(
            plan=plan,
            task_id=task_id,
        )

        if task.status != TaskItemStatus.COMPLETED:
            raise ValueError(
                f"Task '{task_id}' cannot be confirmed because its "
                f"current status is '{task.status}'. "
                "Only COMPLETED tasks may be confirmed."
            )

        task.confirmed = True

    @staticmethod
    def activate_plan(
        *,
        plan: TaskPlan,
    ) -> None:
        """
        Mark a plan that still contains unfinished tasks as ACTIVE.

        Used after every successful planning cycle so a previously
        completed plan status cannot leak over newly planned work.
        """

        if TaskPlanManager.has_remaining_tasks(plan=plan):
            plan.status = TaskPlanStatus.ACTIVE

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
        task.confirmed = False

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

        Planner-generated tasks are reconciled against existing unfinished tasks:
        - If a proposed task matches an existing unfinished task (by objective + dependencies),
          the existing task is preserved with its runtime state (task_id, evidence, confirmed,
          blockers, attempt_count, max_attempts).
        - If no match is found, the proposed task is added as new work (PENDING).
        - Unfinished tasks with no matching proposal are preserved as-is.

        The TaskPlanManager, not the Planner, owns task lifecycle state.
        """

        # --------------------------------------------------------------
        # Preserve immutable execution history.
        # --------------------------------------------------------------

        completed_tasks = [
            task for task in plan.tasks if task.status == TaskItemStatus.COMPLETED
        ]

        # Get existing unfinished tasks (IN_PROGRESS, FAILED, BLOCKED, CANCELLED, PENDING, READY)
        existing_unfinished = [
            task
            for task in plan.tasks
            if task.status != TaskItemStatus.COMPLETED
        ]

        # --------------------------------------------------------------
        # Reconcile planner-proposed tasks with existing unfinished tasks.
        # Conservative matching: exact objective + same dependency set.
        # --------------------------------------------------------------

        # Build a lookup for existing unfinished tasks by (objective, dependencies_tuple)
        existing_by_key = {}
        for task in existing_unfinished:
            key = (task.objective.strip().lower(), tuple(sorted(task.dependencies)))
            if key not in existing_by_key:
                existing_by_key[key] = task

        matched_existing = set()
        replacement_tasks: list[TaskItem] = []

        for proposed_task in tasks:

            if proposed_task.status == TaskItemStatus.COMPLETED:
                raise ValueError(
                    "Planner-generated replacement tasks cannot be " "marked COMPLETED."
                )

            # Try to match with existing unfinished task
            proposed_key = (proposed_task.objective.strip().lower(), tuple(sorted(proposed_task.dependencies)))
            existing_task = existing_by_key.get(proposed_key)

            if existing_task is not None and proposed_key not in matched_existing:
                # Match found: preserve existing task with its runtime state
                # Runtime-owned fields are NEVER silently overwritten:
                #   success_criteria, confirmed, evidence, blockers, attempt_count, max_attempts, status
                #
                # Planner may update:
                #   priority (scheduling policy)
                #   metadata["planner"] namespace (non-conflicting keys)
                #
                # Only an explicit contract_revision=True allows success_criteria change,
                # which resets confirmed=False and clears evidence.
                # The flag is consumed (not persisted).

                if proposed_task.contract_revision:
                    # Explicit contract revision: allow success_criteria update
                    if proposed_task.success_criteria:
                        existing_task.success_criteria = proposed_task.success_criteria
                    # Reset confirmation and evidence for revised criteria
                    existing_task.confirmed = False
                    existing_task.evidence.clear()
                    # Consume the flag - do not persist it
                # else: preserve existing success_criteria, confirmed, evidence exactly

                # Priority can be updated by planner (scheduling policy)
                existing_task.priority = proposed_task.priority

                # Metadata: merge only non-conflicting planner keys under separate namespace
                planner_meta = proposed_task.metadata.get("planner", {})
                if planner_meta:
                    existing_meta = existing_task.metadata.get("planner", {})
                    # Only add non-conflicting keys
                    for k, v in planner_meta.items():
                        if k not in existing_meta:
                            existing_meta[k] = v
                    existing_task.metadata["planner"] = existing_meta

                # Keep existing task in its current status (READY, IN_PROGRESS, etc.)
                # but ensure it's not COMPLETED
                if existing_task.status == TaskItemStatus.COMPLETED:
                    existing_task.status = TaskItemStatus.PENDING

                matched_existing.add(proposed_key)
                replacement_tasks.append(existing_task)
            else:
                # No match: this is genuinely new work
                new_task = proposed_task.model_copy(deep=True)
                new_task.status = TaskItemStatus.PENDING
                new_task.attempt_count = 0  # New tasks start with 0 attempts
                new_task.max_attempts = 3   # Default max attempts
                replacement_tasks.append(new_task)

        # --------------------------------------------------------------
        # Preserve unmatched existing unfinished tasks.
        # These are tasks that exist in the plan but weren't in the planner's output.
        # --------------------------------------------------------------

        for task in existing_unfinished:
            key = (task.objective.strip().lower(), tuple(sorted(task.dependencies)))
            if key not in matched_existing:
                replacement_tasks.append(task)

        # --------------------------------------------------------------
        # Final plan: completed + reconciled/replacement tasks
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
    def get_in_progress_tasks(
        *,
        plan: TaskPlan,
    ) -> list[TaskItem]:
        """
        Return all tasks currently in progress.

        Tasks are returned in planner-defined order.
        """
        return [
            task for task in plan.tasks if task.status == TaskItemStatus.IN_PROGRESS
        ]

    @staticmethod
    def start_ready_tasks(
        *,
        plan: TaskPlan,
        limit: int,
    ) -> list[TaskItem]:
        """
        Start up to `limit` READY tasks.

        Tasks are selected in planner-defined order.

        The TaskPlanManager remains the sole owner of TaskItem lifecycle
        transitions. The scheduler decides how many tasks may be admitted;
        this manager performs READY -> IN_PROGRESS.

        Increments attempt_count on each started task.
        Blocks tasks that have exhausted their attempt budget.
        """

        if limit < 1:
            return []

        ready_tasks = TaskPlanManager.get_ready_tasks(
            plan=plan,
        )

        selected_tasks = ready_tasks[:limit]

        for task in selected_tasks:
            # Check attempt budget before starting
            if task.attempt_count >= task.max_attempts:
                raise ValueError(
                    f"Task '{task.task_id}' has exhausted its attempt budget "
                    f"({task.attempt_count}/{task.max_attempts}). "
                    "Cannot start further executions."
                )
            task.status = TaskItemStatus.IN_PROGRESS
            task.attempt_count += 1

        return selected_tasks

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

        return all(task.status == TaskItemStatus.COMPLETED for task in plan.tasks)

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

        return any(task.status != TaskItemStatus.COMPLETED for task in plan.tasks)

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

        status_by_id = {task.task_id: task.status for task in plan.tasks}

        blocked_tasks: list[TaskItem] = []

        for task in plan.tasks:

            if task.status not in (
                TaskItemStatus.PENDING,
                TaskItemStatus.READY,
            ):
                continue

            if any(
                status_by_id.get(dependency) in terminal_blocking_statuses
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
