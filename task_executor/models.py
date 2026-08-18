from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowStatus(StrEnum):
    """
    Lifecycle state of an execution workflow.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStepStatus(StrEnum):
    """
    Lifecycle state of an individual execution step.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionStep(BaseModel):
    """
    A single capability invocation within an execution workflow.
    """

    step_id: str = Field(
        min_length=1,
        description="Unique identifier for this execution step.",
    )

    description: str = Field(
        min_length=1,
        description="Purpose of this execution step.",
    )

    capability: str = Field(
        min_length=1,
        description="Capability selected for this execution step.",
    )

    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Semantic input for the selected capability.",
    )

    status: ExecutionStepStatus = Field(
        default=ExecutionStepStatus.PENDING,
        description="Current lifecycle state of this step.",
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution metadata associated with this step.",
    )


class ExecutionWorkflow(BaseModel):
    """
    Tactical execution workflow for one TaskItem.

    The workflow contains the ordered capability invocations
    designed by the Task Executor.
    """

    workflow_id: str = Field(
        min_length=1,
        description="Unique identifier for this execution workflow.",
    )

    objective: str = Field(
        min_length=1,
        description="Task objective this workflow is intended to accomplish.",
    )

    execution_strategy: str = Field(
        min_length=1,
        description="Tactical strategy used to accomplish the objective.",
    )

    steps: list[ExecutionStep] = Field(
        min_length=1,
        description="Ordered execution steps.",
    )

    status: WorkflowStatus = Field(
        default=WorkflowStatus.PENDING,
        description="Current lifecycle state of the workflow.",
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Runtime metadata associated with the workflow.",
    )


class ExecutorOutput(BaseModel):
    """
    Structured tactical planning output produced by the
    Task Executor.
    """

    execution_strategy: str = Field(
        min_length=1,
        description="Overall tactical strategy for the current objective.",
    )

    workflow: ExecutionWorkflow


class ExecutionContext(BaseModel):
    """
    Structured execution context consumed by the Task Executor.

    Every field is already formatted for direct insertion into
    the executor prompt.
    """

    task_goal: str
    """
    Overall user goal that the current objective contributes to.
    """

    task_metadata: str
    """
    Compact metadata about the current objective.

    May include:
    - task priority
    - completed dependencies
    - execution constraints
    """

    objective: str
    """
    Current objective selected by the Runtime.
    """

    active_memory: str
    """
    Structured task knowledge accumulated so far.
    """

    execution_summary: str
    """
    Compact history of previous execution attempts.
    """

    artifact_catalog: str
    """
    Metadata describing reusable artifacts.
    """

    capabilities: str
    """
    Available capabilities exposed by the Tool Compiler.
    """

    decision_context: str
    """
    Runtime decision context associated with the current
    execution invocation.

    Contains rationale and evidence when the Executor was
    invoked because of a Runtime/Critic decision.

    If no decision context exists, this contains an explicit
    "No runtime decision context available." message.
    """
