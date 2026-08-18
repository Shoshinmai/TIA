from agents.terminal.state import TerminalState
from llm.llmclient import call_groq, call_ollama

from agents.terminal.models import ObservationSummary, TerminalAction

from agents.terminal.utils.chunker import chunk_text

from agents.terminal.prompts.compressor_prompt import (
    TERMINAL_CHUNK_COMPRESSOR_PROMPT,
    TERMINAL_REDUCER_PROMPT,
)

SMALL_OUTPUT_LIMIT = 3000


def terminal_compressor_node(state: TerminalState):

    raw_output = state["raw_observation"]

    if len(raw_output) < SMALL_OUTPUT_LIMIT:

        return {"compressed_observation": raw_output}

    chunks = chunk_text(raw_output, 16000)
    raw_output = raw_output.strip()
    chunk_summaries = []
    print(f"\n[LENGTH OF RAW OBSERVATION] --> {len(raw_output)}")
    print(f"\n[Number of Chunks] --> {int(len(raw_output)/16000)}")
    c = 0 
    for chunk in chunks:
        c+=1
        print(f"\n[Chunk's Length][{c}] --> {len(chunk)}")
        prompt = TERMINAL_CHUNK_COMPRESSOR_PROMPT.format(
            goal=state["goal"],
            command=state["command"], chunk=chunk
        )

        result = call_ollama(prompt, "qwen2.5:7b-instruct-q3_K_M", True, ObservationSummary)

        chunk_summaries.append(result.summary)
    print(f"\n[Lenght of summaries list] --> {len(chunk_summaries)}")
    reducer_prompt = TERMINAL_REDUCER_PROMPT.format(
        goal=state["goal"],
        summaries="\n".join(chunk_summaries)
    )

    final_summary = call_ollama(
        reducer_prompt, "qwen2.5:7b-instruct-q3_K_M", True, ObservationSummary
    )

    print("\n[COMPRESSED OBSERVATION]")

    print(final_summary.summary)

    return {"compressed_observation": final_summary.summary}
