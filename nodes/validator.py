from agents.terminal.state import TerminalState


MULTI_COMMAND_PATTERNS = ["&&", "||", ";", "|"]


def command_validator_node(state: TerminalState):

    command = state["command"].strip()

    # newline check
    if "\n" in command:
        return {
            "valid_command": False,
            "validation_error": "Generate exactly one command.",
        }

    for pattern in MULTI_COMMAND_PATTERNS:

        if pattern in command:

            return {
                "valid_command": False,
                "validation_error": "Generate exactly one command.",
            }

    return {"valid_command": True, "validation_error": ""}
