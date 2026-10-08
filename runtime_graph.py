from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from nodes.critics import (
    terminal_critic_node,
)
from nodes.execution_tracker import execution_tracker_node
from nodes.message_adapter import (
    message_adapter_node,
)
from nodes.planner import (
    terminal_planner_node,
)
from nodes.task_executor import (
    terminal_task_executor_node,
)
from nodes.task_initializer import (
    task_initializer_node,
)

from runtime.concurrent_execution_node import (
    concurrent_execution_node,
)
from runtime.consistency import (
    validate_runtime_consistency,
)

from runtime.nodes import (
    execution_memory_finalize_node,
    runtime_critic_result_node,
    runtime_initialization_node,
    runtime_memory_update_node,
    runtime_output_node,
    runtime_planner_result_node,
    runtime_stage_router,
)

from runtime.stages import (
    RuntimeStage,
)

from state import (
    TerminalState,
)


# ==========================================================
# Checkpointing
# ==========================================================

checkpointer = MemorySaver()


# ==========================================================
# Graph-only routing helpers
# ==========================================================

def runtime_stage_mapping() -> dict:
    """
    Map RuntimeStage values to the canonical runtime graph nodes.

    The Executor stage now always enters the concurrent
    TaskPlan execution path.

    The concurrent scheduler handles:
    - one task
    - multiple independent tasks
    - dependency chains
    - dependency-aware waves

    No separate sequential/concurrent execution router is needed.
    """

    return {
        RuntimeStage.PLANNER: "planner",
        RuntimeStage.EXECUTOR: "concurrent_execution",
        RuntimeStage.CRITIC: "critic",
        RuntimeStage.TERMINATE: "output",
        RuntimeStage.ERROR: "output",
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
    "critic",
    terminal_critic_node,
)


# ==========================================================
# Runtime nodes
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
    "concurrent_execution",
    concurrent_execution_node,
)

builder.add_node(
    "runtime_critic",
    runtime_critic_result_node,
)

builder.add_node(
    "runtime_consistency",
    validate_runtime_state,
)

# OUTPUT

builder.add_node(
    "output",
    runtime_output_node,
)

# ==========================================================
# Legacy execution nodes
#
# These remain available during migration because their
# functionality has not yet been completely mapped into the
# concurrent execution model.
#
# They are intentionally NOT part of the active execution path.
# ==========================================================

builder.add_node(
    "executor",
    terminal_task_executor_node,
)

builder.add_node(
    "executor_stage",
    lambda state: {},
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
    "execution_memory_finalize",
    execution_memory_finalize_node,
)

builder.add_node(
    "runtime_memory_update",
    runtime_memory_update_node,
)


# ==========================================================
# Entry
# ==========================================================

builder.set_entry_point(
    "task_initializer",
)


# ==========================================================
# Initialization
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
# Canonical TaskPlan Execution
#
# RuntimeStage.EXECUTOR
#       ↓
# concurrent_execution
#
# There is deliberately no executor_mode router here.
# ==========================================================

builder.add_edge(
    "concurrent_execution",
    "runtime_consistency",
)


# ==========================================================
# Runtime Consistency → RuntimeStage routing
#
# The concurrent execution node reaches this boundary with:
#
#   task_plan
#   plan_execution_outcome
#   runtime_state = REVIEWING
#
# Therefore RuntimeStage routing sends execution directly
# to the Critic.
# ==========================================================

builder.add_conditional_edges(
    "runtime_consistency",
    runtime_stage_router,
    runtime_stage_mapping(),
)


# ==========================================================
# Critic
# ==========================================================

builder.add_edge(
    "critic",
    "runtime_critic",
)

builder.add_conditional_edges(
    "runtime_critic",
    runtime_stage_router,
    runtime_stage_mapping(),
)


# ==========================================================
# Output (terminal boundary)
#
# RuntimeStage.TERMINATE / RuntimeStage.ERROR
#       ↓
# output
#       ↓
# END
# ==========================================================

builder.add_edge(
    "output",
    END,
)


# ==========================================================
# Compile
# ==========================================================

runtime_graph = builder.compile()


# ==========================================================
# Optional checkpointed graph
# ==========================================================

# runtime_graph = builder.compile(
#     checkpointer=checkpointer,
# )
