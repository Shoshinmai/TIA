from agents.terminal.result_processing.models import NormalizedResult
from agents.terminal.result_processing.registry import (
    NORMALIZER_REGISTRY,
)


def normalize_result(
    *,
    tool_name: str,
    raw_result: dict,
    attempt: int = 1,
) -> NormalizedResult:
    """
    Normalize a raw tool result into a common semantic format.
    """

    normalizer = NORMALIZER_REGISTRY.get(tool_name)

    if normalizer is None:
        raise ValueError(
            f"No normalizer registered for tool '{tool_name}'."
        )

    return normalizer(
        tool_name=tool_name,
        raw_result=raw_result,
        attempt=attempt,
    )