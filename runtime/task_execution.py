from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from models import ExecutionAttempt
from result_processing.models import (
    RuntimeProcessingResult,
)
from task_executor.models import (
    ExecutionWorkflow,
)


class TaskExecutionStatus(StrEnum):
    """
    Runtime-local lifecycle of one task execution context.
    """

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskExecutionContext(BaseModel):
    """
    Isolated runtime context for one concurrently executing TaskItem.
    """

    execution_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description=("Unique identifier for this task execution instance."),
    )

    plan_id: str = Field(
        min_length=1,
        description="TaskPlan that owns this execution.",
    )

    task_id: str = Field(
        min_length=1,
        description="TaskItem being executed.",
    )

    status: TaskExecutionStatus = Field(
        default=TaskExecutionStatus.CREATED,
        description=("Runtime-local execution lifecycle state."),
    )

    workflow: ExecutionWorkflow | None = Field(
        default=None,
        description=("Workflow associated with this task execution."),
    )

    active_attempt_id: str | None = Field(
        default=None,
        description=("Currently active execution-memory attempt " "for this task."),
    )

    result: dict[str, Any] | None = Field(
        default=None,
        description=("Task-local terminal execution result."),
    )

    error: str | None = Field(
        default=None,
        description=("Task-local execution failure information."),
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=("Additional runtime metadata for this execution."),
    )


class TaskExecutionResult(BaseModel):
    """
    Terminal result returned by AsyncTaskRunner.

    This object communicates everything produced by one task
    execution.

    It does not mutate TaskPlan or central scheduler state.
    """

    execution_id: str = Field(
        min_length=1,
        description=("Task execution context that produced this result."),
    )

    execution_attempt_id: str | None = Field(
        default=None,
        description=(
            "ExecutionMemory attempt that produced this "
            "task result. This identifies the exact task-local "
            "attempt for concurrent reconciliation."
        ),
    )

    execution_attempt: ExecutionAttempt | None = Field(
        default=None,
        description=(
            "Completed task-local ExecutionMemory attempt produced "
            "by this execution. The central reconciler uses this "
            "record to merge the task-local execution history into "
            "authoritative runtime memory."
        ),
    )

    plan_id: str = Field(
        min_length=1,
        description="TaskPlan associated with the execution.",
    )

    task_id: str = Field(
        min_length=1,
        description="TaskItem that was executed.",
    )

    status: TaskExecutionStatus = Field(
        description="Terminal status of the task execution.",
    )

    workflow_id: str | None = Field(
        default=None,
        description=("Workflow used during execution, if one was created."),
    )

    workflow: ExecutionWorkflow | None = Field(
        default=None,
        description=("Serialized workflow used during execution, if one was created."),
    )

    result: dict[str, Any] | None = Field(
        default=None,
        description=("Structured successful execution result."),
    )

    error: str | None = Field(
        default=None,
        description=("Structured or textual failure information."),
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=("Additional execution metadata."),
    )

    processing_results: list[RuntimeProcessingResult] = Field(
        default_factory=list,
        description=(
            "Runtime Processing Pipeline results generated "
            "by the task's workflow steps."
        ),
    )
