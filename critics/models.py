from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class CriticDecision(StrEnum):
    """
    Decision produced by the Critic after evaluating the
    current execution situation.
    """

    CONTINUE_TASK = "continue_task"

    TASK_COMPLETED = "task_completed"

    RETRY_TASK = "retry_task"

    PLAN_UPDATE_REQUIRED = "plan_update_required"

    REPLAN_REQUIRED = "replan_required"

    GOAL_COMPLETED = "goal_completed"


class CriticDecisionScope(StrEnum):
    """
    Scope at which the Critic decision must be interpreted.
    """

    TASK = "task"

    PLAN = "plan"

    GOAL = "goal"


class CriticEvidence(BaseModel):
    """
    A factual piece of evidence supporting the Critic's decision.
    """

    source: str = Field(
        min_length=1,
        description=(
            "Source of the evidence, such as execution memory, "
            "active task memory, artifact catalog, or workflow result."
        ),
    )

    observation: str = Field(
        min_length=1,
        description="Factual observation supporting the decision.",
    )


class CriticOutput(BaseModel):
    """
    Structured semantic evaluation produced by the Critic.

    The Critic evaluates the current execution situation and recommends
    what the Runtime should do next.

    It does not perform the recommended action.
    """

    decision: CriticDecision = Field(
        description="Decision produced by the Critic.",
    )

    scope: CriticDecisionScope = Field(
        description="Scope at which the decision must be applied.",
    )

    target_task_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Task IDs targeted by a task-scoped decision. "
            "Must be empty for plan- and goal-scoped decisions."
        ),
    )

    rationale: str = Field(
        min_length=1,
        description=(
            "Explanation of why this decision is appropriate "
            "given the available evidence."
        ),
    )

    evidence: list[CriticEvidence] = Field(
        min_length=1,
        description=(
            "Factual evidence supporting the decision."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def infer_omitted_scope(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("scope") is not None:
            return value

        decision = value.get("decision")
        decision_value = getattr(decision, "value", decision)
        scope_by_decision = {
            CriticDecision.TASK_COMPLETED.value: CriticDecisionScope.TASK,
            CriticDecision.RETRY_TASK.value: CriticDecisionScope.TASK,
            CriticDecision.GOAL_COMPLETED.value: CriticDecisionScope.GOAL,
        }
        value["scope"] = scope_by_decision.get(
            decision_value,
            CriticDecisionScope.PLAN,
        )
        return value


class CriticContext(BaseModel):
    """
    Structured context supplied to the Critic.

    All fields are already formatted for direct insertion into
    the Critic prompt.

    The Critic receives the relevant execution state rather than
    the raw runtime state.
    """

    overall_goal: str = Field(
        min_length=1,
        description=(
            "Overall user goal represented by the current Task Plan."
        ),
    )

    task_plan_summary: str = Field(
        min_length=1,
        description=(
            "Formatted summary of the current rolling Task Plan, "
            "including task lifecycle state and dependencies."
        ),
    )

    plan_execution_outcome: str = Field(
        min_length=1,
        description=(
            "Formatted description of the most recent concurrent "
            "plan execution outcome."
        ),
    )

    # ----------------------------------------------------------
    # Legacy-compatible field.
    #
    # Kept because the existing context-builder/prompt path still
    # references it. During the next step it will be repurposed
    # from singular current-task wording into execution-situation
    # context.
    # ----------------------------------------------------------

    current_objective: str = Field(
        min_length=1,
        description=(
            "Primary objective or execution situation currently "
            "requiring semantic evaluation."
        ),
    )

    remaining_objectives: str = Field(
        min_length=1,
        description=(
            "Relevant objectives that remain after or around the "
            "current execution situation."
        ),
    )

    execution_summary: str = Field(
        min_length=1,
        description=(
            "Compact summary of execution attempts and outcomes."
        ),
    )

    active_memory: str = Field(
        min_length=1,
        description=(
            "Current task knowledge accumulated during execution."
        ),
    )

    artifact_catalog: str = Field(
        min_length=1,
        description=(
            "Compact metadata catalog of artifacts available as evidence."
        ),
    )