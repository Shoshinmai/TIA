from critics.context_builder import (
    build_critic_context,
)
from critics.integration import build_critic_runtime_event
from critics.models import CriticDecision, CriticOutput
from critics.validator import validate_critic_output
from prompts.critics_prompt import TERMINAL_CRITIC_PROMPT
from llm.llmclient import call_nvidia


def build_goal_completion_correction(
    rejection: list[str],
) -> str:
    """
    Tell the Critic exactly why a previous completion claim was
    refused by deterministic runtime verification.

    The Critic owns the semantic decision. It can only reach that
    decision correctly if it knows which authoritative facts
    contradicted its previous claim.

    Decision-admission refusals (a decision that could not be
    applied to authoritative runtime state at all) use a distinct
    correction block so the Critic re-addresses the contract
    rather than the completion facts.
    """

    if any(
        reason.startswith("ADMISSION")
        for reason in rejection
    ):
        reasons = "\n".join(
            f"- {reason}"
            for reason in rejection
        )

        return (
            "\n\n"
            + "=" * 57
            + "\nDECISION ADMISSION CORRECTION\n"
            + "=" * 57
            + "\n\n"
            "A previous decision could not be applied to "
            "authoritative runtime state.\n\n"
            "Admission failures:\n"
            + reasons
            + "\n\n"
            "Re-read the TASK PLAN SUMMARY. Every target_task_id "
            "must be an existing task ID, TASK_COMPLETED and "
            "RETRY_TASK targets must have a status the decision "
            "type accepts, and target_task_ids must be non-empty "
            "for task-scoped decisions and empty for plan- and "
            "goal-scoped decisions.\n\n"
            "Emit a corrected decision that satisfies both the "
            "output contract and authoritative state.\n\n"
            "Do not repeat a decision that failed admission."
        )

    reasons = "\n".join(
        f"- {reason}"
        for reason in rejection
    )

    return (
        "\n\n"
        + "=" * 57
        + "\nGOAL COMPLETION CORRECTION\n"
        + "=" * 57
        + "\n\n"
        "A previous GOAL_COMPLETED decision for this runtime was "
        "refused by deterministic runtime verification.\n\n"
        "Refusal reasons:\n"
        + reasons
        + "\n\n"
        "If these unresolved facts do not affect the user's goal, "
        "state that explicitly and justify it with concrete "
        "evidence for every unresolved objective.\n\n"
        "If completed tasks with success criteria are unconfirmed, "
        "emit TASK_COMPLETED targeting each of them with "
        "affirmative evidence for their criteria.\n\n"
        "Otherwise choose RETRY_TASK, PLAN_UPDATE_REQUIRED, or "
        "REPLAN_REQUIRED.\n\n"
        "Do not repeat GOAL_COMPLETED without addressing every "
        "reason above."
    )


async def terminal_critic_node(state):    
    """
    Evaluate the current task objective and produce a
    structured CriticOutput.

    The Critic only evaluates and recommends.
    It does not execute the resulting decision.
    """

    print("\n========== CRITIC INPUT ==========")

    critic_context = build_critic_context(
        state=state,
    )

    print("\n----- OVERALL GOAL -----")
    print(
        critic_context.overall_goal
    )

    print("\n----- TASK PLAN SUMMARY -----")
    print(
        critic_context.task_plan_summary
    )

    print("\n----- PLAN EXECUTION OUTCOME -----")
    print(
        critic_context.plan_execution_outcome
    )

    print("\n----- CURRENT EXECUTION SITUATION -----")
    print(
        critic_context.current_objective
    )

    print("\n----- REMAINING OBJECTIVES -----")
    print(
        critic_context.remaining_objectives
    )

    print("\n----- EXECUTION SUMMARY -----")
    print(
        critic_context.execution_summary
    )

    print("\n----- ACTIVE MEMORY -----")
    print(
        critic_context.active_memory
    )

    print("\n----- ARTIFACT CATALOG -----")
    print(
        critic_context.artifact_catalog
    )

    print(
        "\n========== END CRITIC INPUT =========="
    )

    prompt = TERMINAL_CRITIC_PROMPT.format(
        **critic_context.model_dump(),
    )

    rejection = state.get("critic_rejection") or []

    if rejection:
        prompt += build_goal_completion_correction(
            rejection,
        )

    critic_output = await call_nvidia(
        prompt,
        "nvidia/nemotron-3-super-120b-a12b",
        # "nvidia/nemotron-3-ultra-550b-a55b",
        # "openai/gpt-oss-20b",
        subagent=True,
        state_model=CriticOutput,
    )

    # ------------------------------------------------------
    # Structural validation and event mapping are admissions of
    # model output. A structurally invalid decision must not
    # crash the run: it becomes an ADMISSION refusal the Critic
    # gets one bounded chance to correct.
    # ------------------------------------------------------

    try:
        critic_output = validate_critic_output(
            critic_output,
        )

        runtime_event = build_critic_runtime_event(
            critic_output,
        )
    except ValueError as exc:
        print(
            "\n========== CRITIC DECISION REFUSED (ADMISSION) =========="
        )
        print(
            str(exc)
        )

        rejection_reasons = [
            "ADMISSION: The decision failed structural "
            f"validation: {exc} "
            "Produce a corrected decision that satisfies the "
            "output contract: non-empty rationale and "
            "evidence, target_task_ids matching the decision "
            "type and scope, and a scope/decision pair the "
            "validator accepts."
        ]

        return {
            "critic_runtime_event": None,
            "critic_rejection": rejection_reasons,
        }

    print("\n========== CRITIC ==========")
    print(
        critic_output.model_dump()
    )

    print("\n========== CRITIC RUNTIME EVENT ==========")
    print(
        runtime_event
    )

    # ------------------------------------------------------
    # A goal-completion correction stays relevant only while the
    # Critic keeps claiming completion. Any recovery decision
    # clears it.
    # ------------------------------------------------------

    return {
        "critic_output": critic_output,
        "critic_runtime_event": runtime_event,
        "critic_rejection": (
            state.get("critic_rejection")
            if critic_output.decision
            == CriticDecision.GOAL_COMPLETED
            else None
        ),
    }