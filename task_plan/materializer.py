from uuid import uuid4

from agents.terminal.models import (
    PlannerTask,
    TaskPlanningOutput,
)
from agents.terminal.task_plan.manager import TaskPlanManager
from agents.terminal.task_plan.models import (
    TaskItem,
    TaskPlan,
)


class TaskPlanMaterializer:
    """
    Deterministically converts planner output into runtime TaskPlan objects.

    This class performs no reasoning and owns no runtime state.
    """

    @staticmethod
    def materialize(
        *,
        goal: str,
        planning_output: TaskPlanningOutput,
    ) -> TaskPlan:
        """
        Convert planner output into a runtime TaskPlan.
        """

        # ----------------------------------------------------------
        # Pass 1
        # Create runtime task IDs.
        # ----------------------------------------------------------

        id_mapping = {
            task.planner_task_id: str(uuid4()) for task in planning_output.tasks
        }

        # ----------------------------------------------------------
        # Pass 2
        # Create runtime TaskItems.
        # ----------------------------------------------------------

        runtime_tasks: list[TaskItem] = []

        for priority, planner_task in enumerate(planning_output.tasks):

            runtime_tasks.append(
                TaskPlanMaterializer._materialize_task(
                    planner_task=planner_task,
                    task_id=id_mapping[planner_task.planner_task_id],
                    dependency_mapping=id_mapping,
                    priority=priority,
                )
            )

        # ----------------------------------------------------------
        # Create TaskPlan
        # ----------------------------------------------------------

        task_plan = TaskPlan(
            plan_id=str(uuid4()),
            goal=goal,
            tasks=runtime_tasks,
            metadata={
                "strategy": planning_output.strategy,
            },
        )

        # ----------------------------------------------------------
        # Resolve initial task readiness.
        # ----------------------------------------------------------

        TaskPlanManager.update_task_readiness(
            plan=task_plan,
        )

        return task_plan

    # --------------------------------------------------------------
    # Internal Helpers
    # --------------------------------------------------------------

    @staticmethod
    def _materialize_task(
        *,
        planner_task: PlannerTask,
        task_id: str,
        dependency_mapping: dict[str, str],
        priority: int,
    ) -> TaskItem:
        """
        Convert a PlannerTask into a runtime TaskItem.
        """

        runtime_dependencies = []

        for dependency in planner_task.dependencies:

            runtime_dependency_id = dependency_mapping.get(
                dependency
            )

            if runtime_dependency_id is None:
                raise ValueError(
                    "Planner produced an invalid dependency "
                    f"'{dependency}' for task "
                    f"'{planner_task.planner_task_id}'. "
                    "Dependencies must reference another "
                    "planner_task_id from the same planning output."
                )

            runtime_dependencies.append(
                runtime_dependency_id
            )

        return TaskItem(
            task_id=task_id,
            objective=planner_task.objective,
            priority=priority,
            dependencies=runtime_dependencies,
        )
