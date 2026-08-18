from langgraph.graph import END

from agents.terminal.state import TerminalState


# MAX_STEPS = 8


def evaluator_router(state: TerminalState):

    if state["done"]:
        return END

    # if state["step_count"] >= MAX_STEPS:
    #     return END

    return "planner"