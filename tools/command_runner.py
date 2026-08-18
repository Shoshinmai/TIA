from __future__ import annotations

import subprocess
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 15


def run_command(
    command: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """
    Execute one Windows shell command.

    This layer is responsible only for process execution and
    capturing stdout/stderr/return code.

    Semantic interpretation belongs to the result-processing layer.
    """

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""

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
            result.returncode,
        )

        return {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired as exc:

        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(
                "utf-8",
                errors="replace",
            )

        if isinstance(stderr, bytes):
            stderr = stderr.decode(
                "utf-8",
                errors="replace",
            )

        return {
            "stdout": stdout,
            "stderr": (
                f"Command timed out after "
                f"{timeout} seconds." + (f"\n{stderr}" if stderr else "")
            ),
            "returncode": None,
        }

    except Exception as exc:

        return {
            "stdout": "",
            "stderr": str(exc),
            "returncode": -1,
        }
