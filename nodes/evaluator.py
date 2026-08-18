from agents.terminal.models import EvaluatorDecision
import json
from agents.terminal.prompts.evaluator_prompt import TERMINAL_EVALUATOR_PROMPT
from agents.terminal.state import TerminalState
from agents.terminal.utils.evaluator_context_builder import build_evaluator_context
from agents.terminal.utils.evaluator_observation_builder import (
    build_evaluator_observation,
)
from llm.llmclient import call_groq, call_ollama


def terminal_evaluator_node(state: TerminalState):

    observation = state["observation_input"]
    planner_output = state.get("planner_output")

    strategy = ""

    if planner_output is not None:
        strategy = planner_output.planning_step.strategy

    latest_execution = build_evaluator_observation(
    normalized_result=state[
        "runtime_processing_result"
    ].normalized_result,
    artifact_decision=state[
        "runtime_processing_result"
    ].artifact_decision,
)


    execution_summary = build_evaluator_context(state["execution_memory"])

    prompt = TERMINAL_EVALUATOR_PROMPT.format(
        goal=state["goal"],
        strategy=strategy,
        execution_summary=execution_summary,
        latest_execution=latest_execution,
    )
    print("\n[EXECUTION SUMMARY]")
    print(execution_summary)

    print("\n[LATEST TOOL]")
    print(observation.tool_name)

    print("\n[LATEST Execution Summary]")
    print(latest_execution)

    response = call_ollama(
        prompt, "qwen2.5:7b-instruct-q3_K_M", True, EvaluatorDecision
    )
    # response = call_ollama(prompt, "llama3.1:8b", True, EvaluatorDecision)

    # print("\n[EVALUATOR]")
    # print(f"Scratchpad: {state.get("scratchpad", "")}")
    # print(response)

    return {"done": response.decision == "DONE"}
