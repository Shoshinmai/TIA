from __future__ import annotations

from copy import deepcopy
from typing import Any

from models import (
    ActiveTaskMemory,
    ArtifactReference,
    EphemeralExecutionState,
    ExecutionMemory,
    ExecutionAttempt,
    PersistentMemory,
    ThreadMemory,
)
from runtime.models import RuntimeState
from state import TerminalState
from task_plan.models import TaskItem


def _extract_task_relevant_execution_history(
    execution_memory: ExecutionMemory,
    task_id: str,
) -> list[ExecutionAttempt]:
    """
    Extract completed execution attempts relevant to the given task.

    Returns a list of completed (SUCCEEDED/FAILED) attempts that belong
    to this task, based on attempt metadata. Since ExecutionAttempt
    doesn't directly track task_id, we infer from the execution context
    or return all completed attempts as read-only history.
    """
    relevant: list[ExecutionAttempt] = []
    for attempt in execution_memory.attempts:
        if attempt.status.value in ("succeeded", "failed"):
            # Include all completed attempts as execution history.
            # The worker can see what was tried before.
            relevant.append(deepcopy(attempt))
    return relevant


def _build_task_active_memory(
    central_active_memory: ActiveTaskMemory,
    task: TaskItem,
) -> ActiveTaskMemory:
    """
    Build a task-relevant ActiveTaskMemory snapshot.

    Extracts knowledge relevant to this task's objective from the
    central active memory. Returns a new isolated ActiveTaskMemory
    instance with copied data.
    """
    # For now, include all known facts and discovered resources.
    # In future, could filter by relevance to task.objective.
    return ActiveTaskMemory(
        known_facts=list(central_active_memory.known_facts),
        discovered_resources=list(central_active_memory.discovered_resources),
        completed_work=list(central_active_memory.completed_work),
        unresolved_needs=list(central_active_memory.unresolved_needs),
    )


def build_task_execution_snapshot(
    *,
    state: TerminalState,
    task: TaskItem,
) -> dict[str, Any]:
    """
    Build an isolated state snapshot for one task worker.

    The snapshot contains the state needed by TaskWorker and its
    execution-context/result-processing path.

    Workers receive isolated COPIES of relevant prior execution history,
    decision context, and task knowledge. They cannot mutate central
    authoritative state.

    The worker receives an isolated copy of the TaskPlan for
    read-only execution-context construction. The authoritative
    TaskPlan remains owned by the coordinator/reconciler path.
    """

    task_plan = state.get("task_plan")

    if task_plan is None:
        raise ValueError(
            "Cannot build task execution snapshot without a TaskPlan."
        )

    central_execution_memory = state.get("execution_memory", ExecutionMemory())
    central_active_memory = state.get("active_memory", ActiveTaskMemory())
    central_runtime_state = state.get("runtime_state", RuntimeState())

    # Extract task-relevant execution history (completed attempts only)
    prior_attempts = _extract_task_relevant_execution_history(
        central_execution_memory, task.task_id
    )

    # Build worker-local ExecutionMemory with prior attempts as read-only history
    worker_execution_memory = ExecutionMemory()
    worker_execution_memory.attempts = prior_attempts

    # Build task-relevant active memory snapshot
    worker_active_memory = _build_task_active_memory(
        central_active_memory, task
    )

    # Capture the current runtime decision context for the worker
    worker_runtime_state = RuntimeState()
    worker_runtime_state.decision_context = central_runtime_state.decision_context
    worker_runtime_state.iteration = central_runtime_state.iteration
    worker_runtime_state.mode = central_runtime_state.mode
    worker_runtime_state.last_event = central_runtime_state.last_event

    return {
        # ------------------------------------------------------
        # Task-local copy of the plan.
        #
        # Required for execution-context construction, but this
        # is NOT the authoritative scheduling plan.
        # ------------------------------------------------------

        "task_plan": deepcopy(task_plan),
        "task": deepcopy(task),
        "goal": state["goal"],
        "workspace": state.get("workspace"),

        # Worker gets isolated copies with relevant history
        "active_memory": worker_active_memory,
        "execution_memory": worker_execution_memory,

        "artifact_references": deepcopy(state["artifact_references"]),
        "thread_memory": deepcopy(state["thread_memory"]),
        "persistent_memory": deepcopy(state["persistent_memory"]),

        "ephemeral_execution_state": EphemeralExecutionState(),
        "runtime_state": worker_runtime_state,

        "messages": deepcopy(state.get("messages", [])),

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