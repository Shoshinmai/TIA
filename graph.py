from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from agents.terminal.nodes.execution_tracker import execution_tracker_node
from agents.terminal.nodes.task_initializer import task_initializer_node
from agents.terminal.memory.observation_manager import observation_manager_node

# from agents.terminal.nodes.compressor import terminal_compressor_node
from agents.terminal.nodes.evaluator import terminal_evaluator_node
from agents.terminal.nodes.artifact_retriever import artifact_retriever_node
from agents.terminal.nodes.message_adapter import message_adapter_node
from agents.terminal.nodes.planner import terminal_planner_node
from agents.terminal.nodes.tool_compiler import terminal_tool_selector_node
from agents.terminal.nodes.validator import command_validator_node
from agents.terminal.router.evaluator_router import evaluator_router
from agents.terminal.router.safety_router import safety_router
from agents.terminal.router.validator_router import validator_router
from agents.terminal.state import TerminalState
from langgraph.prebuilt import ToolNode
from agents.terminal.tools import TOOLS

# from agents.terminal.nodes.reasoner import terminal_reasoner_node

from agents.terminal.nodes.safety import safety_filter_node

from agents.terminal.nodes.observer import terminal_observer_node

checkpointer = MemorySaver()

builder = StateGraph(TerminalState)
tool_node = ToolNode(TOOLS)
builder.add_node(
    "planner",
    terminal_planner_node,
)

builder.add_node(
    "tool_selector",
    terminal_tool_selector_node,
)
builder.add_node(
    "execution_tracker",
    execution_tracker_node,
)
builder.add_node("tools", tool_node)
builder.add_node("safety_filter", safety_filter_node)

builder.add_node("observer", terminal_observer_node)
builder.add_node("evaluator", terminal_evaluator_node)
builder.add_node("validator", command_validator_node)
# builder.add_node("compressor", terminal_compressor_node)
builder.add_node("observation_manager", observation_manager_node)
builder.add_node(
    "task_initializer",
    task_initializer_node,
)
builder.add_node("artifact_retriever", artifact_retriever_node)
builder.add_node(
    "message_adapter",
    message_adapter_node,
)
builder.set_entry_point("task_initializer")
builder.add_edge("task_initializer", "planner")
builder.add_edge("planner", "tool_selector")
builder.add_edge(
    "tool_selector",
    "execution_tracker",
)

builder.add_edge(
    "execution_tracker",
    "tools",
)
builder.add_edge("tools", "message_adapter")
builder.add_edge("message_adapter", "observation_manager")
builder.add_edge("artifact_retriever", "observer")
builder.add_conditional_edges(
    "validator",
    validator_router,
    {"safety_filter": "safety_filter", "planner": "planner"},
)

builder.add_edge("observation_manager", "observer")
builder.add_edge("observer", "evaluator")
builder.add_conditional_edges(
    "evaluator", evaluator_router, {"planner": "planner", END: END}
)

terminal_graph = builder.compile()
# terminal_graph = builder.compile(checkpointer=checkpointer)
