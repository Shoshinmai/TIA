from agents.terminal.prompts.memory_condenser_prompt import MEMORY_CONDENSER_PROMPT
from agents.terminal.result_processing.models import (
    MemoryUpdateProposal,
)
from llm.llmclient import call_nvidia, call_ollama

def condense_memory(
    *,
    goal: str,
    active_memory: str,
    formatted_observation: str,
    tool_name: str,
) -> MemoryUpdateProposal:

    # parser = PydanticOutputParser(pydantic_object=MemoryUpdateProposal)

    prompt = MEMORY_CONDENSER_PROMPT.format(
        goal=goal,
        active_memory=active_memory,
        formatted_observation=formatted_observation,
        tool_name=tool_name,
    )
    print("\n[FORMATTED OBSERVATION]")
    print(formatted_observation)
    
    # response = call_ollama(
    #     prompt=prompt,
    #     # model="qwen2.5-coder:7b",
    #     # model="qwen2.5:7b-instruct-q3_K_M",
    #     model="freehuntx/qwen3-coder:8b ",
    #     subagent=True,
    #     state_model=MemoryUpdateProposal,
    # )
    
    response = call_nvidia(
        prompt,
        "openai/gpt-oss-20b",
        # "nvidia/nemotron-3-ultra-550b-a55b",
        subagent=True,
        state_model=MemoryUpdateProposal,
    )
    print("\n[CONDENSER RESPONSE]")
    print(response)

    return response
