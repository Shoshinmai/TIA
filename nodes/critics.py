from critics.context_builder import (
    build_critic_context,
)
from critics.integration import build_critic_runtime_event
from critics.models import CriticOutput
from critics.validator import validate_critic_output
from prompts.critics_prompt import TERMINAL_CRITIC_PROMPT
from llm.llmclient import call_nvidia


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

    return {
        "critic_output": critic_output,
        "critic_runtime_event": runtime_event,
    }