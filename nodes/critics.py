from agents.terminal.critics.context_builder import (
    build_critic_context,
)
from agents.terminal.critics.integration import build_critic_runtime_event
from agents.terminal.critics.models import CriticOutput
from agents.terminal.critics.validator import validate_critic_output
from agents.terminal.prompts.critics_prompt import TERMINAL_CRITIC_PROMPT
from llm.llmclient import call_nvidia


def terminal_critic_node(state):
    """
    Evaluate the current task objective and produce a
    structured CriticOutput.

    The Critic only evaluates and recommends.
    It does not execute the resulting decision.
    """

    critic_context = build_critic_context(
        state=state,
    )

    print("\n========== CRITIC CONTEXT ==========")
    print(critic_context.model_dump())

    prompt = TERMINAL_CRITIC_PROMPT.format(**critic_context.model_dump())

    critic_output = call_nvidia(
        prompt,
        # "nvidia/nemotron-3-super-120b-a12b",
        # "nvidia/nemotron-3-ultra-550b-a55b",
        "openai/gpt-oss-20b",
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
