
from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


class AgenticLoopAction(StrEnum):
    """Actions the agent can select during an iteration."""

    CAPABILITY = "CAPABILITY"
    COMPLEX_EXECUTION = "COMPLEX_EXECUTION"
    FINISH = "FINISH"
    CLARIFICATION = "CLARIFICATION"


class AgenticLoopDecision(BaseModel):
    """
    Structured decision made by the autonomous problem-solving agent.

    This model describes the next action only. It does not execute
    capabilities, perform complex work, or certify goal completion.

    Action validation checks the fields essential to each action.
    The caller must dispatch on ``action`` and use only the fields
    relevant to that action.
    """

    action: AgenticLoopAction = Field(
        description="The single action selected for this iteration.",
    )

    rationale: str = Field(
        min_length=1,
        description=(
            "Why this action is appropriate given the goal, current "
            "context, and observations."
        ),
    )

    capability_name: str | None = Field(
        default=None,
        description=(
            "Exact name of an available capability. Required when "
            "action is CAPABILITY."
        ),
    )

    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arguments for the selected capability, matching its "
            "input schema. Used only for CAPABILITY."
        ),
    )

    final_response: str | None = Field(
        default=None,
        description=(
            "Grounded user-facing outcome when action is FINISH. "
            "May describe complete, partial, blocked, or inconclusive work."
        ),
    )

    clarification_question: str | None = Field(
        default=None,
        description=(
            "One clear question requesting essential missing "
            "information when action is CLARIFICATION."
        ),
    )

    completion_evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Evidence supporting any completion claim. An empty list "
            "is valid when the outcome is incomplete or inconclusive."
        ),
    )

    @model_validator(mode="after")
    def validate_required_action_fields(self) -> Self:
        """Validate fields required to execute the selected action."""

        if not self.rationale.strip():
            raise ValueError("rationale must not be empty.")

        if self.action == AgenticLoopAction.CAPABILITY:
            if (
                self.capability_name is None
                or not self.capability_name.strip()
            ):
                raise ValueError(
                    "CAPABILITY requires a non-empty capability_name."
                )

        elif self.action == AgenticLoopAction.FINISH:
            if (
                self.final_response is None
                or not self.final_response.strip()
            ):
                raise ValueError(
                    "FINISH requires a non-empty final_response."
                )

        elif self.action == AgenticLoopAction.CLARIFICATION:
            if (
                self.clarification_question is None
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
    """
    Result returned when one standalone loop invocation stops.

    FINISHED means the loop selected FINISH and has a user-facing
    outcome to report. It does not independently certify that the
    user's overall goal was achieved.
    """

    status: AgenticLoopStatus = Field(
        description="Why the loop invocation stopped.",
    )

    decisions_made: int = Field(
        default=0,
        ge=0,
        description=(
            "Number of agent decisions made during this invocation."
        ),
    )

    final_response: str | None = Field(
        default=None,
        description=(
            "User-facing outcome, when available. May describe "
            "partial or incomplete work."
        ),
    )

    clarification_question: str | None = Field(
        default=None,
        description=(
            "Question to return to the user when clarification is required."
        ),
    )

    rationale: str | None = Field(
        default=None,
        description="Explanation of the stopping decision.",
    )

    completion_evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Evidence collected to support any reported completion."
        ),
    )

    observations: list[str] = Field(
        default_factory=list,
        description=(
            "Observed capability results accumulated during the loop."
        ),
    )

    error: str | None = Field(
        default=None,
        description=(
            "Error information when execution or decision processing fails."
        ),
    )

    @model_validator(mode="after")
    def validate_status_contract(self) -> Self:
        """Ensure the result contains information required by its status."""

        if self.status == AgenticLoopStatus.FINISHED:
            if (
                self.final_response is None
                or not self.final_response.strip()
            ):
                raise ValueError(
                    "FINISHED requires a non-empty final_response."
                )

        elif self.status == AgenticLoopStatus.CLARIFICATION_REQUIRED:
            if (
                self.clarification_question is None
                or not self.clarification_question.strip()
            ):
                raise ValueError(
                    "CLARIFICATION_REQUIRED requires a non-empty "
                    "clarification_question."
                )

        elif self.status == AgenticLoopStatus.FAILED:
            if self.error is None or not self.error.strip():
                raise ValueError(
                    "FAILED requires a non-empty error."
                )

        return self
