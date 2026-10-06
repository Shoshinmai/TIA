from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from runtime.plan_execution_outcome import PlanExecutionCondition


class OutputType(StrEnum):
    FINAL = "final"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutputOutcome(BaseModel):
    condition: PlanExecutionCondition

    completed_task_ids: list[str] = Field(
        default_factory=list,
    )

    failed_task_ids: list[str] = Field(
        default_factory=list,
    )

    blocked_task_ids: list[str] = Field(
        default_factory=list,
    )

    cancelled_task_ids: list[str] = Field(
        default_factory=list,
    )


class OutputTaskSummary(BaseModel):
    task_id: str
    objective: str
    status: str

    blockers: list[str] = Field(
        default_factory=list,
    )


class OutputKnowledge(BaseModel):
    known_facts: list[str] = Field(
        default_factory=list,
    )

    completed_work: list[str] = Field(
        default_factory=list,
    )

    discovered_resources: list[str] = Field(
        default_factory=list,
    )

    unresolved_needs: list[str] = Field(
        default_factory=list,
    )


class OutputExecutionSummary(BaseModel):
    total_attempts: int = 0

    successful_attempts: int = 0

    failed_attempts: int = 0

    important_errors: list[str] = Field(
        default_factory=list,
    )

    important_results: list[str] = Field(
        default_factory=list,
    )


class OutputArtifact(BaseModel):
    artifact_id: str

    artifact_type: str

    summary: str = ""

    source: str


class OutputDecision(BaseModel):
    rationale: str

    evidence: list[str] = Field(
        default_factory=list,
    )


class OutputContext(BaseModel):
    """
    Bounded, output-specific representation of authoritative
    Terminal Agent state.

    This model intentionally does not expose TerminalState,
    raw execution objects, or raw artifact contents.
    """

    goal: str

    output_type: OutputType

    outcome: OutputOutcome

    tasks: list[OutputTaskSummary] = Field(
        default_factory=list,
    )

    knowledge: OutputKnowledge = Field(
        default_factory=OutputKnowledge,
    )

    execution: OutputExecutionSummary = Field(
        default_factory=OutputExecutionSummary,
    )

    artifacts: list[OutputArtifact] = Field(
        default_factory=list,
    )

    decision: OutputDecision | None = None


class AgentOutput(BaseModel):
    """
    User-facing output produced by the Output Layer.
    """

    output_type: OutputType

    message: str = Field(
        min_length=1,
    )


OUTPUT_FALLBACK_MESSAGES: dict[OutputType, str] = {
    OutputType.FINAL: (
        "The requested work was completed, "
        "but I could not generate the final summary."
    ),
    OutputType.BLOCKED: (
        "I could not complete the request because "
        "the current task state is blocked."
    ),
    OutputType.FAILED: (
        "I could not complete the requested work."
    ),
    OutputType.CANCELLED: (
        "The agent run was cancelled before the "
        "requested work was completed."
    ),
}