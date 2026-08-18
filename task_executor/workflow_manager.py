from __future__ import annotations

from agents.terminal.task_executor.models import (
    ExecutionStep,
    ExecutionStepStatus,
    ExecutionWorkflow,
    WorkflowStatus,
)


class WorkflowManager:
    """
    Deterministic owner of ExecutionWorkflow lifecycle.

    The manager controls workflow and step state transitions.

    It does not:
    - execute capabilities
    - select capabilities
    - call the LLM
    - retry failed steps
    - call the Critic
    - perform replanning
    """


    @staticmethod
    def start(
        *,
        workflow: ExecutionWorkflow,
    ) -> None:
        """
        Start a pending workflow.
        """

        if workflow.status != WorkflowStatus.PENDING:
            raise ValueError(
                f"Cannot start workflow in status "
                f"'{workflow.status}'."
            )

        if not workflow.steps:
            raise ValueError(
                "Cannot start a workflow without execution steps."
            )

        workflow.status = WorkflowStatus.IN_PROGRESS


    @staticmethod
    def get_current_step(
        workflow: ExecutionWorkflow,
    ) -> ExecutionStep | None:
        """
        Return the next pending execution step.

        Steps are executed sequentially.
        """

        if workflow.status != WorkflowStatus.IN_PROGRESS:
            return None

        for step in workflow.steps:
            if step.status == ExecutionStepStatus.PENDING:
                return step

        return None


    @staticmethod
    def start_step(
        *,
        workflow: ExecutionWorkflow,
        step_id: str,
    ) -> None:
        """
        Mark the current pending step as in progress.
        """

        WorkflowManager._require_workflow_in_progress(
            workflow
        )

        step = WorkflowManager._find_step(
            workflow=workflow,
            step_id=step_id,
        )

        if step.status != ExecutionStepStatus.PENDING:
            raise ValueError(
                f"Cannot start step '{step_id}' "
                f"in status '{step.status}'."
            )

        current_step = WorkflowManager.get_current_step(
            workflow
        )

        if current_step is None:
            raise ValueError(
                "Workflow has no pending execution step."
            )

        if current_step.step_id != step_id:
            raise ValueError(
                f"Step '{step_id}' is not the current "
                f"execution step."
            )

        step.status = ExecutionStepStatus.IN_PROGRESS


    @staticmethod
    def complete_step(
        *,
        workflow: ExecutionWorkflow,
        step_id: str,
    ) -> None:
        """
        Mark an in-progress step as completed.

        If this was the final step, the workflow becomes completed.
        """

        WorkflowManager._require_workflow_in_progress(
            workflow
        )

        step = WorkflowManager._find_step(
            workflow=workflow,
            step_id=step_id,
        )

        if step.status != ExecutionStepStatus.IN_PROGRESS:
            raise ValueError(
                f"Cannot complete step '{step_id}' "
                f"in status '{step.status}'."
            )

        step.status = ExecutionStepStatus.COMPLETED

        if WorkflowManager.get_current_step(workflow) is None:
            workflow.status = WorkflowStatus.COMPLETED


    @staticmethod
    def fail_step(
        *,
        workflow: ExecutionWorkflow,
        step_id: str,
    ) -> None:
        """
        Mark an in-progress step as failed and pause the workflow.

        Recovery decisions are intentionally outside this manager.
        """

        WorkflowManager._require_workflow_in_progress(
            workflow
        )

        step = WorkflowManager._find_step(
            workflow=workflow,
            step_id=step_id,
        )

        if step.status != ExecutionStepStatus.IN_PROGRESS:
            raise ValueError(
                f"Cannot fail step '{step_id}' "
                f"in status '{step.status}'."
            )

        step.status = ExecutionStepStatus.FAILED

        workflow.status = WorkflowStatus.PAUSED


    @staticmethod
    def pause(
        *,
        workflow: ExecutionWorkflow,
    ) -> None:
        """
        Pause an in-progress workflow.
        """

        if workflow.status != WorkflowStatus.IN_PROGRESS:
            raise ValueError(
                f"Cannot pause workflow in status "
                f"'{workflow.status}'."
            )

        workflow.status = WorkflowStatus.PAUSED


    @staticmethod
    def resume(
        *,
        workflow: ExecutionWorkflow,
    ) -> None:
        """
        Resume a paused workflow.

        A workflow containing a failed step cannot be resumed
        directly because recovery must first be decided by the
        higher-level orchestration layer.
        """

        if workflow.status != WorkflowStatus.PAUSED:
            raise ValueError(
                f"Cannot resume workflow in status "
                f"'{workflow.status}'."
            )

        failed_steps = [
            step
            for step in workflow.steps
            if step.status == ExecutionStepStatus.FAILED
        ]

        if failed_steps:
            raise ValueError(
                "Cannot resume a workflow containing failed steps. "
                "Recovery must be resolved by the higher-level "
                "orchestration layer."
            )

        workflow.status = WorkflowStatus.IN_PROGRESS


    @staticmethod
    def cancel(
        *,
        workflow: ExecutionWorkflow,
    ) -> None:
        """
        Cancel a workflow that has not already completed or failed.
        """

        if workflow.status in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }:
            raise ValueError(
                f"Cannot cancel workflow in status "
                f"'{workflow.status}'."
            )

        workflow.status = WorkflowStatus.CANCELLED


    @staticmethod
    def _find_step(
        *,
        workflow: ExecutionWorkflow,
        step_id: str,
    ) -> ExecutionStep:
        """
        Find an execution step by ID.
        """

        for step in workflow.steps:
            if step.step_id == step_id:
                return step

        raise ValueError(
            f"Execution step '{step_id}' not found."
        )


    @staticmethod
    def _require_workflow_in_progress(
        workflow: ExecutionWorkflow,
    ) -> None:
        """
        Ensure the workflow is currently executable.
        """

        if workflow.status != WorkflowStatus.IN_PROGRESS:
            raise ValueError(
                f"Workflow must be in progress, "
                f"current status is '{workflow.status}'."
            )