from langchain_core.tools import tool

from tools.command_runner import run_command


@tool
async def run_terminal(command: str) -> dict:
    """
    Execute exactly one terminal command asynchronously.

    This is the fallback terminal capability of the Terminal Agent.

    Specialized capabilities should be preferred when they directly
    satisfy the objective.

    The command may be read-only or modifying depending on the
    current objective.

    Shell syntax:
    - Commands run in bash (POSIX syntax): single quotes, pipes,
      redirection, && chaining and globbing all work.
    - Do not use cmd.exe builtins such as dir, cls, type or copy.
    - Prefer bash builtins and standard POSIX utilities.

    Command rules:
    - Exactly one command.
    - Never chain commands.
    - Do not use && or ||.
    - Do not use multiple independent commands.
    - The command must directly contribute to the current objective.
    - Output must be plain text or JSON. Do not attempt to modify
      agent memory, plans or runtime state through this capability.

    Returns:
        success
        output
        error
        return_code
    """

    result = await run_command(command)

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