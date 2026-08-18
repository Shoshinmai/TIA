from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agents.terminal.nodes.critics import (
    terminal_critic_node,
)
from agents.terminal.nodes.execution_tracker import execution_tracker_node
from agents.terminal.nodes.message_adapter import (
    message_adapter_node,
)
from agents.terminal.nodes.planner import (
    terminal_planner_node,
)
from agents.terminal.nodes.task_executor import (
    terminal_task_executor_node,
)
from agents.terminal.nodes.task_initializer import (
    task_initializer_node,
)

from agents.terminal.runtime.consistency import (
    validate_runtime_consistency,
)

from agents.terminal.runtime.nodes import (
    execution_memory_finalize_node,
    runtime_critic_result_node,
    runtime_initialization_node,
    runtime_memory_update_node,
    runtime_planner_result_node,
    runtime_stage_router,
    runtime_workflow_execution_node,
)

from agents.terminal.runtime.stages import (
    RuntimeStage,
)

from agents.terminal.state import (
    TerminalState,
)


# ==========================================================
# Checkpointing
# ==========================================================

checkpointer = MemorySaver()


# ==========================================================
# Graph-only routing helpers
# ==========================================================


def executor_stage_router(
    state: TerminalState,
) -> str:
    """
    Decide whether the Executor must generate a workflow or
    the Execution Tracker may begin the next workflow step.

    A workflow is executable only while it still has pending work.
    A completed workflow is treated as stale and requires a new
    workflow to be generated.
    """

    workflow = state.get(
        "execution_workflow",
    )

    if workflow is None:
        return "executor"

    # ----------------------------------------------------------
    # A completed workflow cannot be resumed.
    #
    # This can occur after RETRY_TASK if an old workflow has
    # survived an earlier runtime transition.
    # ----------------------------------------------------------

    if workflow.status.value == "completed":
        return "executor"

    # ----------------------------------------------------------
    # Active workflow → tracker starts the next attempt.
    # ----------------------------------------------------------

    return "execution_tracker"


def runtime_stage_mapping() -> dict:
    """
    Map RuntimeStage values to graph nodes.
    """

    return {
        RuntimeStage.PLANNER: "planner",
        RuntimeStage.EXECUTOR: "executor_stage",
        RuntimeStage.CRITIC: "critic",
        RuntimeStage.TERMINATE: END,
        RuntimeStage.ERROR: END,
    }


# ==========================================================
# Runtime consistency validation
# ==========================================================


def validate_runtime_state(
    state: TerminalState,
) -> dict:
    """
    Validate cross-subsystem runtime consistency.

    Validation is intentionally side-effect free.

    This function exists as a graph boundary between state
    mutation and subsequent Runtime routing.
    """

    validate_runtime_consistency(
        state,
    )

    return {}


# ==========================================================
# Graph
# ==========================================================

builder = StateGraph(
    TerminalState,
)


# ==========================================================
# Core Terminal Agent nodes
# ==========================================================

builder.add_node(
    "task_initializer",
    task_initializer_node,
)

builder.add_node(
    "planner",
    terminal_planner_node,
)

builder.add_node(
    "executor",
    terminal_task_executor_node,
)

builder.add_node(
    "critic",
    terminal_critic_node,
)


# ==========================================================
# Runtime adapter nodes
# ==========================================================

builder.add_node(
    "runtime_initialization",
    runtime_initialization_node,
)

builder.add_node(
    "planner_runtime",
    runtime_planner_result_node,
)

builder.add_node(
    "executor_stage",
    lambda state: {},
)

builder.add_node(
    "workflow_execution",
    runtime_workflow_execution_node,
)

builder.add_node(
    "execution_tracker",
    execution_tracker_node,
)

builder.add_node(
    "message_adapter",
    message_adapter_node,
)

builder.add_node(
    "runtime_memory_update",
    runtime_memory_update_node,
)

builder.add_node(
    "critic_runtime",
    runtime_critic_result_node,
)

builder.add_node(
    "execution_memory_finalize",
    execution_memory_finalize_node,
)

# ==========================================================
# Runtime consistency node
# ==========================================================

builder.add_node(
    "runtime_consistency",
    validate_runtime_state,
)


# ==========================================================
# Entry
# ==========================================================

builder.set_entry_point(
    "task_initializer",
)


# ==========================================================
# Initialization
#
# task_initializer
#       ↓
# runtime_initialization
#       ↓
# RuntimeStage routing
# ==========================================================

builder.add_edge(
    "task_initializer",
    "runtime_initialization",
)


builder.add_conditional_edges(
    "runtime_initialization",
    runtime_stage_router,
    runtime_stage_mapping(),
)


# ==========================================================
# Planner
#
# planner
#       ↓
# planner_runtime
#       ↓
# runtime_consistency
#       ↓
# RuntimeStage routing
# ==========================================================

builder.add_edge(
    "planner",
    "planner_runtime",
)


builder.add_conditional_edges(
    "planner_runtime",
    runtime_stage_router,
    runtime_stage_mapping(),
)


# ==========================================================
# Executor Stage
#
# RuntimeStage.EXECUTOR
#       ↓
# executor_stage
#       │
#       ├── no workflow
#       │       ↓
#       │    executor
#       │
#       └── workflow exists
#               ↓
#        workflow_execution
# ==========================================================

builder.add_conditional_edges(
    "executor_stage",
    executor_stage_router,
    {
        "executor": "executor",
        "execution_tracker": "execution_tracker",
    },
)

builder.add_edge(
    "execution_tracker",
    "workflow_execution",
)


# ==========================================================
# Executor
#
# The Task Executor generates an ExecutionWorkflow.
#
# executor
#       ↓
# workflow_execution
# ==========================================================

builder.add_edge(
    "executor",
    "runtime_consistency",
)


# ==========================================================
# Workflow execution
#
# workflow_execution
#       ↓
# message_adapter
#       ↓
# runtime_memory_update
#       ↓
# runtime_consistency
#       ↓
# RuntimeStage routing
#
# Incomplete workflow:
#
#     EXECUTING
#         ↓
#     executor_stage
#         ↓
# workflow_execution
#
# Completed workflow:
#
#     EXECUTION_COMPLETED
#         ↓
#      REVIEWING
#         ↓
#       critic
# ==========================================================

builder.add_edge(
    "workflow_execution",
    "message_adapter",
)


builder.add_edge(
    "message_adapter",
    "execution_memory_finalize",
)

builder.add_edge(
    "execution_memory_finalize",
    "runtime_memory_update",
)


builder.add_edge(
    "runtime_memory_update",
    "runtime_consistency",
)


# ==========================================================
# Shared Runtime Consistency → RuntimeStage routing
#
# This is intentionally shared by:
#
#   planner_runtime
#   runtime_memory_update
#   critic_runtime
#
# because validation is purely state-based.
# ==========================================================

builder.add_conditional_edges(
    "runtime_consistency",
    runtime_stage_router,
    runtime_stage_mapping(),
)


# ==========================================================
# Critic
#
# critic
#       ↓
# critic_runtime
#       ↓
# runtime_consistency
#       ↓
# RuntimeStage routing
# ==========================================================

builder.add_edge(
    "critic",
    "critic_runtime",
)


builder.add_conditional_edges(
    "critic_runtime",
    runtime_stage_router,
    runtime_stage_mapping(),
)


# ==========================================================
# Compile
# ==========================================================

runtime_graph = builder.compile()


# ==========================================================
# Optional checkpointed graph
#
# If checkpoint persistence is required:
#
# runtime_graph = builder.compile(
#     checkpointer=checkpointer,
# )
# ==========================================================
