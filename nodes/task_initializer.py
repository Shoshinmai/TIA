from langchain_core.runnables import RunnableConfig

from agents.terminal.models import (
    ActiveTaskMemory,
    EphemeralExecutionState,
    ExecutionMemory,
    PersistentMemory,
    TaskContext,
    ThreadMemory,
)
from agents.terminal.runtime.models import RuntimeState
from agents.terminal.state import TerminalState


# async def task_initializer_node(
def task_initializer_node(
    state: TerminalState,
    config: RunnableConfig,
) -> dict:
    """
    Initialize state for a new Terminal Agent task.

    Creates fresh task-scoped and execution-scoped state while
    retaining thread-scoped memory restored by the LangGraph
    checkpointer.
    """

    goal = state["goal"]

    thread_id = config.get("configurable", {}).get("thread_id")

    if not thread_id:
        raise ValueError("Terminal Agent requires a LangGraph thread_id.")

    existing_thread_memory = state.get("thread_memory")

    thread_memory = (
        existing_thread_memory if existing_thread_memory is not None else ThreadMemory()
    )

    task = TaskContext(
        goal=goal,
        thread_id=str(thread_id),
    )

    return {
        "task": task,
        "active_memory": ActiveTaskMemory(),
        "execution_memory": ExecutionMemory(),
        "artifact_references": [],
        "thread_memory": thread_memory,
        "task_plan": None,
        "execution_workflow": None,
        "critic_runtime_event": None,
        "runtime_state": RuntimeState(),
        "persistent_memory": PersistentMemory(),
        "ephemeral_execution_state": EphemeralExecutionState(),
        # Transitional legacy reset
        "action_type": "",
        "thought": "",
        "command": "",
        "tool_name": "",
        "tool_input": "",
        "success": False,
        "error": "",
        "done": False,
        "step_count": 0,
        "scratchpad": "",
        "valid_command": False,
        "validation_error": "",
        "safety_passed": False,
        "safety_reason": "",
        "raw_observation": "",
        "compressed_observation": "",
        "observation_input": None,
        "artifact_ids": [],
        "observation_summary": "",
        "observation_conclusion": "",
        "planner_output": None,
    }
