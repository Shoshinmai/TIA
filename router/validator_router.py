from agents.terminal.state import TerminalState


def validator_router(state: TerminalState):

    if state["valid_command"]:
        return "safety_filter"

    return "planner"