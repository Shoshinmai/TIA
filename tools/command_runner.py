from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 120


def _find_bash() -> str | None:
    """
    Locate a bash executable on Windows.

    A Git installation ships bash but does not necessarily place it
    on PATH, so the Git executable location is used to discover it.
    """

    bash = shutil.which("bash")

    if bash:
        return bash

    git = shutil.which("git")

    if git:

        git_root = Path(git).resolve().parent.parent

        for candidate in (
            git_root / "bin" / "bash.exe",
            git_root / "usr" / "bin" / "bash.exe",
        ):

            if candidate.is_file():
                return str(candidate)

    for root in (
        Path("C:/Program Files/Git"),
        Path("C:/Program Files (x86)/Git"),
    ):

        for candidate in (
            root / "bin" / "bash.exe",
            root / "usr" / "bin" / "bash.exe",
        ):

            if candidate.is_file():
                return str(candidate)

    return None


def resolve_shell() -> tuple[list[str], str]:
    """
    Resolve the shell used to execute one terminal command.

    Agent-generated commands are written in POSIX shell syntax.
    On Windows the default shell is cmd.exe, which does not support
    that syntax. Bash is therefore preferred when it is available.

    The returned value contains the argument prefix and a label used
    for logging.
    """

    if os.name != "nt":
        return [], "posix-shell"

    bash = _find_bash()

    if bash:
        return [bash, "-c"], "bash"

    for candidate, prefix in (
        ("pwsh", ["-NoProfile", "-Command"]),
        ("powershell", ["-NoProfile", "-Command"]),
    ):

        executable = shutil.which(candidate)

        if executable:
            return [executable, *prefix], candidate

    return [], "cmd"


async def run_command(
    command: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """
    Execute one shell command asynchronously.

    This layer is responsible only for process execution and
    capturing stdout/stderr/return code.

    Semantic interpretation belongs to the result-processing layer.
    """

    shell_prefix, shell_label = resolve_shell()

    print(
        "[COMMAND RUNNER SHELL]",
        shell_label,
    )

    try:

        if shell_prefix:

            process = await asyncio.create_subprocess_exec(
                *shell_prefix,
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        else:

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )

        except asyncio.TimeoutError:
            process.kill()

            stdout_bytes, stderr_bytes = await process.communicate()

            stdout = stdout_bytes.decode(
                "utf-8",
                errors="replace",
            )

            stderr = stderr_bytes.decode(
                "utf-8",
                errors="replace",
            )

            return {
                "stdout": stdout,
                "stderr": (
                    f"Command timed out after "
                    f"{timeout} seconds."
                    + (
                        f"\n{stderr}"
                        if stderr
                        else ""
                    )
                ),
                "returncode": None,
            }

        except asyncio.CancelledError:
            # A cancelled agent run must not leave its shell process running.
            if process.returncode is None:
                process.kill()
                await process.communicate()
            raise

        stdout = stdout_bytes.decode(
            "utf-8",
            errors="replace",
        )

        stderr = stderr_bytes.decode(
            "utf-8",
            errors="replace",
        )

        print(
            "[COMMAND RUNNER]",
            repr(command),
        )

        print(
            "[COMMAND RUNNER STDOUT]",
            repr(stdout),
        )

        print(
            "[COMMAND RUNNER STDERR]",
            repr(stderr),
        )

        print(
            "[COMMAND RUNNER RETURN CODE]",
            process.returncode,
        )

        return {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": process.returncode,
        }

    except Exception as exc:

        return {
            "stdout": "",
            "stderr": str(exc),
            "returncode": -1,
        }
