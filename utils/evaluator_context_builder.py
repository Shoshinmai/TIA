from __future__ import annotations

from agents.terminal.models import ExecutionMemory, ExecutionAttempt


def build_evaluator_context(
    execution_memory: ExecutionMemory,
    *,
    previous_attempt_limit: int = 3,
) -> str:
    """
    Build a compact execution summary for the Evaluator.

    The Evaluator does not need the full ExecutionMemory. Instead, it
    receives a concise summary of recent execution history so it can
    determine whether the user's goal has been completed.
    """

    attempts = execution_memory.attempts

    if not attempts:
        return "No execution attempts have been made."

    latest = attempts[-1]
    print(latest)

    lines: list[str] = []

    lines.append(f"Total Attempts: {len(attempts)}")
    lines.append("")
    lines.append("Latest Attempt")
    lines.append("--------------")
    lines.extend(_format_attempt(latest))

    previous = attempts[:-1]

    if previous:
        lines.append("")
        lines.append("Previous Attempts")
        lines.append("-----------------")

        for index, attempt in enumerate(
            reversed(previous[-previous_attempt_limit:]),
            start=1,
        ):
            lines.append(f"{index}.")
            lines.extend(
                f"  {line}" for line in _format_attempt(attempt)
            )
            lines.append("")

    return "\n".join(lines).rstrip()


def _format_attempt(attempt) -> list[str]:
    """
    Format a single execution attempt into a concise summary.   
    """

    artifact_count = len(attempt.artifact_ids)

    return [
        f"Capability: {attempt.capability}",
        f"Status: {attempt.status.value}",
        f"Progress Made: {'Yes' if attempt.progress_made else 'No'}",
        f"Outcome: {attempt.outcome or 'N/A'}",
        f"Artifacts: {artifact_count}",
    ]