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
    """

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

    critic_output = validate_critic_output(
        critic_output,
    )

    runtime_event = build_critic_runtime_event(
        critic_output,
    )

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