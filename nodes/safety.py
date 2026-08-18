from agents.terminal.state import TerminalState


BLOCKED_PATTERNS = [
    "del ",
    "rmdir ",
    "rm ",
    "format ",
    "shutdown ",
    "taskkill ",
    "reg delete ",
]


def safety_filter_node(state: TerminalState):

    command = state["command"].lower()

    for pattern in BLOCKED_PATTERNS:

        if pattern in command:

            return {
                "safety_passed": False,
                "safety_reason": "Blocked command pattern detected.",
            }

    return {"safety_passed": True, "safety_reason": ""}
