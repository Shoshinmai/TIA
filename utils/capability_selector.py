from langchain_core.tools import BaseTool

from agents.terminal.tools import TOOLS


def get_candidate_tools(
    state,
) -> list[BaseTool]:
    """
    Retrieve candidate capabilities for the current planning step.

    Current strategy:
        Return all registered tools.

    Future strategy:
        • Semantic retrieval
        • Embedding search
        • Capability ranking
        • Context-aware filtering

    The Planner should never know how the tools were selected.
    """

    goal = state.get("goal", "")

    scratchpad = state.get("scratchpad", "")

    # Placeholder so future retrieval already has
    # access to planner context.
    _ = (goal, scratchpad)

    return TOOLS
