from langgraph.graph import END

from agents.terminal.state import TerminalState


def safety_router(state: TerminalState):

    if state["safety_passed"]:
        return "executor"

    return END