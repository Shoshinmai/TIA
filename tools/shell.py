from langchain_core.tools import tool

from agents.terminal.tools.command_runner import run_command


@tool
def run_terminal(command: str) -> dict:
    """
    Execute exactly one Windows terminal command.

    This is the fallback terminal capability of the Terminal Agent.

    Specialized capabilities should be preferred when they directly
    satisfy the objective.

    The command may be read-only or modifying depending on the
    current objective.

    Command rules:
    - Exactly one command.
    - Never chain commands.
    - Do not use && or ||.
    - Do not use multiple independent commands.
    - The command must directly contribute to the current objective.

    Returns:
        success
        output
        error
        return_code
    """

    result = run_command(command)

    # command_runner currently exposes `returncode`.
    # Keep the adapter tolerant of the normalized `return_code`
    # spelling as well.
    return_code = result.get(
        "return_code",
        result.get("returncode", -1),
    )

    return {
        "success": return_code == 0,
        "output": result.get("stdout", ""),
        "error": result.get("stderr", ""),
        "return_code": return_code,
    }


# print(
#     run_terminal.invoke(
#         {"command": "where python"}
#     )
# )