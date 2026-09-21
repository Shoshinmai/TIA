from __future__ import annotations

import asyncio
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 30


async def run_command(
    command: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """
    Execute one Windows shell command asynchronously.

    This layer is responsible only for process execution and
    capturing stdout/stderr/return code.

    Semantic interpretation belongs to the result-processing layer.
    """

    try:
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
