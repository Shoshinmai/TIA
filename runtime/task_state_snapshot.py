from __future__ import annotations

from copy import deepcopy
from typing import Any

from models import (
    ActiveTaskMemory,
    ArtifactReference,
    EphemeralExecutionState,
    ExecutionMemory,
    PersistentMemory,
    ThreadMemory,
)
from runtime.models import RuntimeState
from state import TerminalState
from task_plan.models import TaskItem


def build_task_execution_snapshot(
    *,
    state: TerminalState,
    task: TaskItem,
) -> dict[str, Any]:
    """
    Build an isolated state snapshot for one task worker.

    The snapshot contains the state needed by TaskWorker and its
    execution-context/result-processing path.

    Mutable task/execution structures are copied so one worker
    cannot mutate another worker's state.

    The worker receives an isolated copy of the TaskPlan for
    read-only execution-context construction. The authoritative
    TaskPlan remains owned by the coordinator/reconciler path.
    """

    task_plan = state.get("task_plan")

    if task_plan is None:
        raise ValueError(
            "Cannot build task execution snapshot without a TaskPlan."
        )

    return {
        # ------------------------------------------------------
        # Task-local copy of the plan.
        #
        # Required for execution-context construction, but this
        # is NOT the authoritative scheduling plan.
        # ------------------------------------------------------

        "task_plan": deepcopy(
            task_plan
        ),

        "task": deepcopy(
            task
        ),

        "goal": state["goal"],

        "active_memory": deepcopy(
            state["active_memory"]
        ),

        "execution_memory": ExecutionMemory(),

        "artifact_references": deepcopy(
            state["artifact_references"]
        ),

        "thread_memory": deepcopy(
            state["thread_memory"]
        ),

        "persistent_memory": deepcopy(
            state["persistent_memory"]
        ),

        "ephemeral_execution_state": (
            EphemeralExecutionState()
        ),

        "runtime_state": RuntimeState(),

        "messages": deepcopy(
            state.get(
                "messages",
                [],
            )
        ),

        # ------------------------------------------------------
        # Worker-local legacy/result-processing fields.
        # ------------------------------------------------------

        "action_type": "",
        "thought": "",
        "command": "",
        "tool_name": "",
        "tool_input": "",
        "success": False,
        "error": "",
        "done": False,
        "step_count": 0,
        "valid_command": False,
        "validation_error": "",
        "safety_passed": False,
        "safety_reason": "",
        "raw_observation": "",
        "observation_input": None,
        "runtime_processing_result": None,
        "artifact_ids": [],
        "planner_output": None,

        # ------------------------------------------------------
        # Explicit task identity.
        # ------------------------------------------------------

        "task_id": task.task_id,
    }