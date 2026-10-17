
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from tools import TOOLS
from utils.memory_formatter import (
    format_active_memory,
    format_execution_summary,
    format_task_plan,
)


# Initial prompt-context budgets. These are character limits, not token limits.
MAX_GOAL_CHARS = 4_000
MAX_LOOP_CONTEXT_CHARS = 8_000
MAX_CAPABILITIES_CHARS = 8_000
MAX_OBSERVATIONS_CHARS = 6_000

MAX_OBSERVATION_COUNT = 10
MAX_OBSERVATION_CHARS = 1_500
MAX_CAPABILITY_DESCRIPTION_CHARS = 1_000


class AgenticLoopContext(BaseModel):
    """Bounded, prompt-ready context for one agentic-loop decision."""

    goal: str = Field(
        min_length=1,
        description="Original user objective.",
    )

    loop_context: str = Field(
        min_length=1,
        description="Bounded summary of the current task situation.",
    )

    available_capabilities: str = Field(
        min_length=1,
        description="Capability descriptions and input schemas.",
    )

    observations: str = Field(
        min_length=1,
        description="Bounded history of observed action results.",
    )


def build_agentic_loop_context(
    state: Mapping[str, Any],
    observations: Sequence[str] | None = None,
    capabilities: Sequence[Any] | None = None,
    *,
    goal: str | None = None,
) -> AgenticLoopContext:
    """
    Build bounded context for AGENTIC_LOOP_PROMPT.

    This function only formats existing information. It does not execute
    capabilities, select actions, infer goal completion, or mutate state.

    Args:
        state: Current state mapping. Existing TerminalState fields are
            read when available; raw state is never serialized wholesale.
        observations: Results of previously executed actions, supplied by
            the caller in chronological order.
        capabilities: Optional capability list. Defaults to tools.TOOLS.
        goal: Optional explicit original goal. When omitted, the goal is
            derived from state["task"].goal or state["goal"].

    Returns:
        An AgenticLoopContext whose fields match the prompt placeholders.

    Raises:
        ValueError: If the original goal cannot be determined.
    """

    resolved_goal = _resolve_goal(state, goal)

    return AgenticLoopContext(
        goal=_truncate(resolved_goal, MAX_GOAL_CHARS),
        loop_context=_build_loop_context(state),
        available_capabilities=_build_capabilities(
            TOOLS if capabilities is None else capabilities,
        ),
        observations=_build_observations(observations or ()),
    )


def _resolve_goal(
    state: Mapping[str, Any],
    explicit_goal: str | None,
) -> str:
    """Resolve the original task goal without inventing a fallback."""

    if explicit_goal is not None and explicit_goal.strip():
        return explicit_goal.strip()

    task = state.get("task")
    task_goal = getattr(task, "goal", None)

    if isinstance(task_goal, str) and task_goal.strip():
        return task_goal.strip()

    state_goal = state.get("goal")

    if isinstance(state_goal, str) and state_goal.strip():
        return state_goal.strip()

    raise ValueError(
        "Cannot build AgenticLoopContext without an original task goal."
    )


def _build_loop_context(state: Mapping[str, Any]) -> str:
    """Format selected task state into a bounded, readable summary."""

    sections: list[str] = []

    workspace = state.get("workspace")
    if isinstance(workspace, str) and workspace.strip():
        sections.extend(
            [
                "## Workspace",
                workspace.strip(),
            ]
        )

    active_memory = state.get("active_memory")
    if active_memory is not None:
        try:
            memory_text = format_active_memory(active_memory)
        except (AttributeError, TypeError, ValueError):
            memory_text = "Active memory could not be formatted."

        sections.extend(
            [
                "",
                "## Active Task Memory",
                memory_text,
            ]
        )
    else:
        sections.extend(
            [
                "",
                "## Active Task Memory",
                "No active task memory available.",
            ]
        )

    task_plan = state.get("task_plan")
    if task_plan is not None:
        try:
            plan_text = format_task_plan(task_plan)
        except (AttributeError, TypeError, ValueError):
            plan_text = "The current task plan could not be formatted."

        sections.extend(
            [
                "",
                "## Current Task Plan",
                plan_text,
            ]
        )

    execution_memory = state.get("execution_memory")
    if execution_memory is not None:
        try:
            execution_text = format_execution_summary(execution_memory)
        except (AttributeError, TypeError, ValueError):
            execution_text = "Execution history could not be formatted."

        sections.extend(
            [
                "",
                "## Recent Execution History",
                execution_text,
            ]
        )
    else:
        sections.extend(
            [
                "",
                "## Recent Execution History",
                "No execution history available.",
            ]
        )

    plan_outcome = state.get("plan_execution_outcome")
    if plan_outcome is not None:
        sections.extend(
            [
                "",
                "## Latest Plan Execution Outcome",
                _format_plan_outcome(plan_outcome),
            ]
        )

    runtime_state = state.get("runtime_state")
    if runtime_state is not None:
        runtime_lines: list[str] = []

        last_event = getattr(runtime_state, "last_event", None)
        if last_event is not None:
            runtime_lines.append(
                f"Last runtime event: {getattr(last_event, 'value', last_event)}"
            )

        iteration = getattr(runtime_state, "iteration", None)
        if iteration is not None:
            runtime_lines.append(f"Runtime iteration: {iteration}")

        if runtime_lines:
            sections.extend(
                [
                    "",
                    "## Runtime Situation",
                    *runtime_lines,
                ]
            )

    if not sections:
        context = "No additional task context is available."
    else:
        context = "\n".join(sections).strip()

    return _truncate(context, MAX_LOOP_CONTEXT_CHARS)


def _format_plan_outcome(outcome: Any) -> str:
    """Expose selected outcome fields rather than a raw object dump."""

    lines: list[str] = []

    condition = getattr(outcome, "condition", None)
    if condition is not None:
        lines.append(
            f"Condition: {getattr(condition, 'value', condition)}"
        )

    for field_name, label in (
        ("completed_task_ids", "Completed task IDs"),
        ("failed_task_ids", "Failed task IDs"),
        ("blocked_task_ids", "Blocked task IDs"),
        ("cancelled_task_ids", "Cancelled task IDs"),
    ):
        values = getattr(outcome, field_name, None)
        if values is not None:
            rendered = ", ".join(str(value) for value in values) or "None"
            lines.append(f"{label}: {rendered}")

    return "\n".join(lines) or "No structured outcome details available."


def _build_capabilities(capabilities: Sequence[Any]) -> str:
    """
    Format the available capability interface.

    Only capability metadata and input schemas are included. Capability
    implementations, internal objects, and execution results are excluded.
    """

    entries: list[str] = []

    for capability in capabilities:
        name = getattr(capability, "name", None)
        if not isinstance(name, str) or not name.strip():
            continue

        description = getattr(capability, "description", "")
        if not isinstance(description, str):
            description = ""

        description = _truncate(
            description.strip(),
            MAX_CAPABILITY_DESCRIPTION_CHARS,
        )

        schema = _get_capability_schema(capability)

        entry = [
            f"Name: {name}",
            f"Description: {description or 'No description provided.'}",
            "Input schema:",
            json.dumps(schema, ensure_ascii=False, indent=2),
        ]
        entries.append("\n".join(entry))

    if not entries:
        rendered = "No capabilities are available."
    else:
        rendered = "\n\n".join(entries)

    return _truncate(rendered, MAX_CAPABILITIES_CHARS)


def _get_capability_schema(capability: Any) -> dict[str, Any]:
    """Return a JSON-compatible argument schema when available."""

    schema_source = getattr(capability, "args_schema", None)

    if schema_source is None:
        return {}

    try:
        if isinstance(schema_source, type) and issubclass(
            schema_source,
            BaseModel,
        ):
            schema = schema_source.model_json_schema()

        elif isinstance(schema_source, BaseModel):
            schema = schema_source.__class__.model_json_schema()

        elif isinstance(schema_source, dict):
            schema = schema_source

        else:
            return {}

        # Round-trip to ensure the result can be serialized as JSON.
        return json.loads(json.dumps(schema, ensure_ascii=False))

    except (AttributeError, TypeError, ValueError, TypeError):
        return {}


def _build_observations(observations: Sequence[str]) -> str:
    """Keep the newest observations and bound both entries and total text."""

    recent = list(observations)[-MAX_OBSERVATION_COUNT:]

    if not recent:
        return "No previous action observations."

    lines: list[str] = []

    for index, observation in enumerate(recent, start=1):
        if not isinstance(observation, str):
            rendered = str(observation)
        else:
            rendered = observation

        rendered = _truncate(
            rendered.strip(),
            MAX_OBSERVATION_CHARS,
        )

        lines.append(f"{index}. {rendered or '(empty observation)'}")

    return _truncate("\n".join(lines), MAX_OBSERVATIONS_CHARS)


def _truncate(text: str, limit: int) -> str:
    """Truncate text with an explicit marker when the limit is exceeded."""

    if len(text) <= limit:
        return text

    marker = "\n...[truncated to fit context budget]"
    available = max(0, limit - len(marker))

    return text[:available] + marker
