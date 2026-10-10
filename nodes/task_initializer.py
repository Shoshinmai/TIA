from langchain_core.runnables import RunnableConfig
from pathlib import Path

from models import (
    ActiveTaskMemory,
    EphemeralExecutionState,
    ExecutionMemory,
    PersistentMemory,
    TaskContext,
    ThreadMemory,
)
from runtime.models import RuntimeState
from state import TerminalState
from utils.location_resolver import set_workspace_root


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

    Resolves the workspace root in priority order:
    1. Explicit workspace from request state
    2. Configured workspace fallback (if configuration system exists)
    3. Current working directory (session CWD)
    4. Explicit unavailable sentinel if none valid

    Never uses the goal text as a filesystem path.
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

    # Resolve workspace root - never use goal text as fallback
    workspace = _resolve_workspace_root(state)

    # Create runtime state and anchor workspace root
    runtime_state = RuntimeState()
    if workspace != "workspace:unavailable":
        runtime_state.metadata["workspace_root"] = workspace
        # Also set in location resolver for tool access (session-wide)
        set_workspace_root(workspace)

    return {
        "task": task,
        "active_memory": ActiveTaskMemory(),
        "execution_memory": ExecutionMemory(),
        "artifact_references": [],
        "thread_memory": thread_memory,
        "task_plan": None,
        "execution_workflow": None,
        "critic_runtime_event": None,
        "runtime_state": runtime_state,
        "concurrent_execution": True,
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
        "workspace": workspace,
    }


def _resolve_workspace_root(state: TerminalState) -> str:
    """
    Resolve the workspace root for this run.

    Priority order:
    1. Explicit workspace from request/state
    2. Configured workspace fallback (not implemented yet)
    3. Current working directory (session CWD)
    4. Explicit unavailable sentinel

    Never uses goal text as a filesystem path.
    """
    # 1. Explicit workspace from request/state
    explicit_workspace = state.get("workspace")
    if explicit_workspace:
        path = Path(explicit_workspace)
        if path.exists() and path.is_dir():
            return str(path.resolve())
        # If explicit workspace doesn't exist, fall through to CWD

    # 2. Configured workspace fallback - placeholder for future config system
    # configured_workspace = get_configured_workspace()
    # if configured_workspace:
    #     path = Path(configured_workspace)
    #     if path.exists() and path.is_dir():
    #         return str(path.resolve())

    # 3. Current working directory (session CWD)
    cwd = Path.cwd()
    if cwd.exists() and cwd.is_dir():
        return str(cwd.resolve())

    # 4. Explicit unavailable sentinel
    return "workspace:unavailable"
