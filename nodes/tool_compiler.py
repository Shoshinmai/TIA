from __future__ import annotations

from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from agents.terminal.task_executor.models import ExecutionStep
from agents.terminal.tools import TOOLS


def compile_execution_step(
    step: ExecutionStep,
    tools: list[BaseTool] | None = None,
) -> AIMessage:

    available_tools = tools if tools is not None else TOOLS

    tool_map = {
        tool.name: tool
        for tool in available_tools
    }

    tool = tool_map.get(step.capability)

    if tool is None:
        raise ValueError(
            f"Unknown capability '{step.capability}'. "
            f"Available capabilities: "
            f"{', '.join(sorted(tool_map))}"
        )

    unresolved_references = _find_unresolved_references(
        step.arguments,
    )

    if unresolved_references:

        raise ValueError(
            "ExecutionStep contains unresolved workflow "
            "references. ExecutionWorkflow does not support "
            "runtime output interpolation.\n"
            + "\n".join(
                f"- {reference}"
                for reference in unresolved_references
            )
        )

    arguments = _validate_arguments(
        tool=tool,
        arguments=step.arguments,
    )

    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": tool.name,
                "args": arguments,
                "id": f"call_{uuid4().hex}",
                "type": "tool_call",
            }
        ],
    )

def _find_unresolved_references(
    value: Any,
    *,
    path: str = "arguments",
) -> list[str]:
    """
    Find unresolved workflow-output references inside tool arguments.

    ExecutionWorkflow currently does not support runtime output
    interpolation.

    The only syntax treated as a workflow reference is the explicit
    '${...}' form.

    Ordinary shell syntax such as PowerShell:
        ForEach-Object { ... }

    must remain valid.
    """

    references: list[str] = []

    if isinstance(value, str):

        if "${" in value:
            references.append(
                f"{path}: {value}"
            )

        return references

    if isinstance(value, dict):

        for key, nested_value in value.items():
            references.extend(
                _find_unresolved_references(
                    nested_value,
                    path=f"{path}.{key}",
                )
            )

        return references

    if isinstance(value, list):

        for index, nested_value in enumerate(value):
            references.extend(
                _find_unresolved_references(
                    nested_value,
                    path=f"{path}[{index}]",
                )
            )

        return references

    return references

def _validate_arguments(
    *,
    tool: BaseTool,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate and normalize arguments against the capability schema.
    """

    if tool.args_schema is None:
        return arguments

    try:
        validated = tool.args_schema.model_validate(
            arguments
        )
    except Exception as exc:
        raise ValueError(
            f"Invalid arguments for capability "
            f"'{tool.name}': {exc}"
        ) from exc

    return validated.model_dump(
        exclude_none=True
    )