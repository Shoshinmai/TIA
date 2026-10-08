from critics.models import (
    CriticDecision,
    CriticDecisionScope,
    CriticOutput,
)


def validate_critic_output(
    critic_output: CriticOutput,
) -> CriticOutput:
    """
    Deterministically validate the structural contract of a
    CriticOutput.

    This validator is intentionally structural only.

    It does NOT attempt to determine whether the Critic's semantic
    decision is correct or whether the supplied evidence is
    sufficient to establish the user's goal.

    Evidence sufficiency is a semantic judgment owned by the Critic.
    A single authoritative observation may be sufficient for a
    small, self-contained task, while a broader task may require
    multiple observations.
    """

    # ==========================================================
    # Basic output contract
    # ==========================================================

    if not critic_output.rationale.strip():
        raise ValueError(
            "CriticOutput rationale cannot be empty."
        )

    if not critic_output.evidence:
        raise ValueError(
            "CriticOutput must contain at least one "
            "piece of evidence."
        )

    for index, evidence in enumerate(
        critic_output.evidence
    ):
        if not evidence.source.strip():
            raise ValueError(
                f"Critic evidence at index {index} "
                "has an empty source."
            )

        if not evidence.observation.strip():
            raise ValueError(
                f"Critic evidence at index {index} "
                "has an empty observation."
            )

    # ==========================================================
    # Decision / Scope Contract
    # ==========================================================

    decision = critic_output.decision
    scope = critic_output.scope
    targets = critic_output.target_task_ids

    # ----------------------------------------------------------
    # TASK-SCOPED DECISIONS
    # ----------------------------------------------------------

    task_scoped_decisions = {
        CriticDecision.TASK_COMPLETED,
        CriticDecision.RETRY_TASK,
    }

    # ----------------------------------------------------------
    # PLAN-SCOPED DECISIONS
    # ----------------------------------------------------------

    plan_scoped_decisions = {
        CriticDecision.CONTINUE_TASK,
        CriticDecision.PLAN_UPDATE_REQUIRED,
        CriticDecision.REPLAN_REQUIRED,
    }

    # ----------------------------------------------------------
    # GOAL-SCOPED DECISIONS
    # ----------------------------------------------------------

    goal_scoped_decisions = {
        CriticDecision.GOAL_COMPLETED,
    }

    # ----------------------------------------------------------
    # Task-scoped decisions
    # ----------------------------------------------------------

    if decision in task_scoped_decisions:

        if scope != CriticDecisionScope.TASK:
            raise ValueError(
                f"Critic decision '{decision.value}' must "
                "use TASK scope."
            )

        if not targets:
            raise ValueError(
                f"Critic decision '{decision.value}' requires "
                "at least one target_task_id."
            )

        for task_id in targets:
            if not task_id.strip():
                raise ValueError(
                    "Critic target_task_ids cannot contain "
                    "empty task IDs."
                )

    # ----------------------------------------------------------
    # Plan-scoped decisions
    # ----------------------------------------------------------

    elif decision in plan_scoped_decisions:

        if scope != CriticDecisionScope.PLAN:
            raise ValueError(
                f"Critic decision '{decision.value}' must "
                "use PLAN scope."
            )

        if targets:
            raise ValueError(
                f"Critic decision '{decision.value}' must not "
                "contain target_task_ids."
            )

    # ----------------------------------------------------------
    # Goal-scoped decisions
    # ----------------------------------------------------------

    elif decision in goal_scoped_decisions:

        if scope != CriticDecisionScope.GOAL:
            raise ValueError(
                f"Critic decision '{decision.value}' must "
                "use GOAL scope."
            )

        if targets:
            raise ValueError(
                f"Critic decision '{decision.value}' must not "
                "contain target_task_ids."
            )

    # ==========================================================
    # No semantic evidence validation here.
    # ==========================================================
    #
    # The Critic is responsible for deciding whether the supplied
    # evidence is sufficient for its semantic decision.
    #
    # The validator only guarantees that evidence exists and is
    # structurally valid.
    #
    # Therefore:
    #
    #   1 evidence item  -> valid
    #   2 evidence items -> valid
    #   N evidence items -> valid
    #
    # provided each item has a source and observation.
    #
    # GOAL_COMPLETED specifically does NOT require:
    #
    #   - a minimum evidence count,
    #   - completion keywords,
    #   - goal-related keywords,
    #   - plan-exhaustion keywords,
    #   - or any other deterministic interpretation of prose.
    #
    # Semantic evidence sufficiency belongs to the Critic.
    # ==========================================================

    return critic_output