import json

from langchain_core.messages import ToolMessage

from agents.terminal.memory.execution_manager import ExecutionMemoryManager
from agents.terminal.state import TerminalState
from agents.terminal.models import ObservationInput
from agents.terminal.result_processing.processor import (
    process_tool_result,
)


def message_adapter_node(state: TerminalState):

    messages = state["messages"]

    latest_tool_message = None

    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            latest_tool_message = message
            print(f"\nLATEST TOOL MESSAGE --> {latest_tool_message}")
            break

    if latest_tool_message is None:
        raise ValueError("No ToolMessage found.")

    try:
        raw_result = json.loads(latest_tool_message.content)

    except json.JSONDecodeError:
        raw_result = latest_tool_message.content

    processed_result = process_tool_result(
        state=state,
        tool_name=latest_tool_message.name,
        raw_result=raw_result,
        attempt=1,
    )
    print("\n========== RUNTIME PROCESSING ==========")
    print(processed_result)
    print(state["success"])
    success = raw_result.get("success", True) if isinstance(raw_result, dict) else True

    ephemeral = state.get("ephemeral_execution_state")

    if ephemeral is not None and ephemeral.current_attempt_id is not None:
        ExecutionMemoryManager.finish_attempt(
            execution_memory=state["execution_memory"],
            attempt_id=ephemeral.current_attempt_id,
            runtime_result=processed_result,
            success=success,
            error=None,
        )
    print("[MESSAGE ADAPTER]")
    print("Current Attempt:", ephemeral)

    observation_input = ObservationInput(
        source="tool",
        tool_name=latest_tool_message.name,
        success=(
            raw_result.get("success", True) if isinstance(raw_result, dict) else True
        ),
        raw_result=raw_result,
    )

    print("\n[MESSAGE ADAPTER]")
    print(observation_input)
    return {
        "observation_input": observation_input,
        "runtime_processing_result": processed_result,
        "execution_memory": state["execution_memory"],
    }
