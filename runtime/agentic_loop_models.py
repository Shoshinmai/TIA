from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


class AgenticLoopAction(StrEnum):
    """Actions the agent can select during an iteration."""

    CAPABILITY = "CAPABILITY"
    CONSULT_CRITIC = "CONSULT_CRITIC"
    COMPLEX_EXECUTION = "COMPLEX_EXECUTION"
    FINISH = "FINISH"
    CLARIFICATION = "CLARIFICATION"


class AgenticLoopDecision(BaseModel):
    """Structured next-action decision made by the main agent."""

    action: AgenticLoopAction = Field(
        description="The single action selected for this iteration.",
    )
    rationale: str = Field(
        min_length=1,
        description="Why this action is appropriate.",
    )

    capability_name: str | None = Field(
        default=None,
        description="Exact registered capability name for CAPABILITY.",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments for the selected capability.",
    )

    critic_question: str | None = Field(
        default=None,
        description=(
            "Specific question to ask the advisory critic. Required "
            "when action is CONSULT_CRITIC."
        ),
    )
    critic_observation_sequences: list[int] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Sequence numbers of observations relevant to the critic "
            "question. Leave empty to include the recent observations."
        ),
    )
    critic_proposed_approach: str | None = Field(
        default=None,
        max_length=2_000,
        description=(
            "Optional approach the main agent wants the critic to assess."
        ),
    )

    final_response: str | None = Field(
        default=None,
        description=(
            "Grounded user-facing outcome when action is FINISH. "
            "It may describe complete, partial, blocked, or inconclusive work."
        ),
    )
    clarification_question: str | None = Field(
        default=None,
        description=(
            "One clear question requesting essential missing information."
        ),
    )
    completion_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence supporting any completion claim.",
    )

    @model_validator(mode="after")
    def validate_required_action_fields(self) -> Self:
        if not self.rationale.strip():
            raise ValueError("rationale must not be empty.")

        if self.action == AgenticLoopAction.CAPABILITY:
            if not self.capability_name or not self.capability_name.strip():
                raise ValueError(
                    "CAPABILITY requires a non-empty capability_name."
                )

        elif self.action == AgenticLoopAction.CONSULT_CRITIC:
            if not self.critic_question or not self.critic_question.strip():
                raise ValueError(
                    "CONSULT_CRITIC requires a non-empty critic_question."
                )

            if any(
                sequence < 1
                for sequence in self.critic_observation_sequences
            ):
                raise ValueError(
                    "critic_observation_sequences must contain "
                    "positive sequence numbers."
                )

            if self.critic_proposed_approach is not None:
                if not self.critic_proposed_approach.strip():
                    self.critic_proposed_approach = None

        elif self.action == AgenticLoopAction.FINISH:
            if not self.final_response or not self.final_response.strip():
                raise ValueError(
                    "FINISH requires a non-empty final_response."
                )

        elif self.action == AgenticLoopAction.CLARIFICATION:
            if (
                not self.clarification_question
                or not self.clarification_question.strip()
            ):
                raise ValueError(
                    "CLARIFICATION requires a non-empty "
                    "clarification_question."
                )

        return self


class AgenticLoopStatus(StrEnum):
    """Reasons a standalone loop invocation can stop."""

    FINISHED = "finished"
    COMPLEX_EXECUTION_REQUESTED = "complex_execution_requested"
    CLARIFICATION_REQUIRED = "clarification_required"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


class AgenticLoopResult(BaseModel):
    """Result returned when one standalone loop invocation stops."""

    status: AgenticLoopStatus
    decisions_made: int = Field(default=0, ge=0)
    critic_responses_received: int = Field(default=0, ge=0)

    final_response: str | None = None
    clarification_question: str | None = None
    rationale: str | None = None
    completion_evidence: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def validate_status_contract(self) -> Self:
        if self.status == AgenticLoopStatus.FINISHED:
            if not self.final_response or not self.final_response.strip():
                raise ValueError(
                    "FINISHED requires a non-empty final_response."
                )

        elif self.status == AgenticLoopStatus.CLARIFICATION_REQUIRED:
            if (
                not self.clarification_question
                or not self.clarification_question.strip()
            ):
                raise ValueError(
                    "CLARIFICATION_REQUIRED requires a non-empty "
                    "clarification_question."
                )

        elif self.status == AgenticLoopStatus.FAILED:
            if not self.error or not self.error.strip():
                raise ValueError("FAILED requires a non-empty error.")

        return self