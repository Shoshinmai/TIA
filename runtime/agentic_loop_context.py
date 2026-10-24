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
from utils.tool_prompt_builder import (
    get_capability_metadata,
    get_capability_schema,
)


# These are character budgets, not tokenizer-based token budgets.
MAX_GOAL_CHARS = 4_000
MAX_LOOP_CONTEXT_CHARS = 8_000
MAX_CAPABILITIES_CHARS = 8_000
MAX_OBSERVATIONS_CHARS = 6_000

MAX_OBSERVATION_COUNT = 10
MAX_OBSERVATION_CHARS = 1_500
MAX_CAPABILITY_DESCRIPTION_CHARS = 1_000

_CAPABILITY_OMISSION_MARKER = (
    "[Some capabilities omitted because their complete descriptions "
    "and schemas would exceed the capability context budget.]"
)


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
        description="Capability descriptions and complete input schemas.",
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
    """Build bounded context matching the agentic-loop prompt placeholders.

    This function formats existing information only. It does not execute
    capabilities, select actions, infer goal completion, or mutate state.

    The original goal can be supplied explicitly or resolved from
    state["task"].goal or the legacy state["goal"] field.
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
    """Resolve the original goal without inventing a fallback."""
    if isinstance(explicit_goal, str) and explicit_goal.strip():
        return explicit_goal.strip()

    task = state.get("task")
    task_goal = (
        task.get("goal") if isinstance(task, Mapping) else getattr(task, "goal", None)
    )

    if isinstance(task_goal, str) and task_goal.strip():
        return task_goal.strip()

    state_goal = state.get("goal")
    if isinstance(state_goal, str) and state_goal.strip():
        return state_goal.strip()

    raise ValueError("Cannot build AgenticLoopContext without an original task goal.")


def _build_loop_context(state: Mapping[str, Any]) -> str:
    """Format selected state fields without serializing the entire state."""
    sections: list[str] = []

    workspace = state.get("workspace")
    if isinstance(workspace, str) and workspace.strip():
        sections.extend(["## Workspace", workspace.strip()])

    recent_actions = state.get("agentic_loop_recent_actions") or []
    if recent_actions:
        sections.extend(
            [
                "",
                "## Recent Actions Already Attempted",
                *[
                    f"{index}. {action}"
                    for index, action in enumerate(recent_actions, start=1)
                ],
                (
                    "Avoid repeating an action that has already produced "
                    "sufficient evidence. Repeat it only when there is a "
                    "specific reason to expect a different or missing result."
                ),
            ]
        )

    active_memory = state.get("active_memory")
    if active_memory is None:
        memory_text = "No active task memory available."
    else:
        try:
            memory_text = format_active_memory(active_memory)
        except (AttributeError, TypeError, ValueError):
            memory_text = "Active memory could not be formatted."

    sections.extend(["", "## Active Task Memory", memory_text])

    task_plan = state.get("task_plan")
    if task_plan is None:
        plan_text = "No task plan exists."
    else:
        try:
            plan_text = format_task_plan(task_plan)
        except (AttributeError, TypeError, ValueError):
            plan_text = "The current task plan could not be formatted."

    sections.extend(["", "## Current Task Plan", plan_text])

    execution_memory = state.get("execution_memory")
    if execution_memory is None:
        execution_text = "No execution history available."
    else:
        try:
            execution_text = format_execution_summary(execution_memory)
        except (AttributeError, TypeError, ValueError):
            execution_text = "Execution history could not be formatted."

    sections.extend(["", "## Recent Execution History", execution_text])

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
                "Last runtime event: " f"{getattr(last_event, 'value', last_event)}"
            )

        iteration = getattr(runtime_state, "iteration", None)
        if iteration is not None:
            runtime_lines.append(f"Runtime iteration: {iteration}")

        if runtime_lines:
            sections.extend(["", "## Runtime Situation", *runtime_lines])

    context = "\n".join(sections).strip()
    if not context:
        context = "No additional task context is available."

    return _truncate(context, MAX_LOOP_CONTEXT_CHARS)


def _format_plan_outcome(outcome: Any) -> str:
    """Expose selected outcome fields rather than a raw object dump."""
    lines: list[str] = []

    condition = getattr(outcome, "condition", None)
    if condition is not None:
        lines.append(f"Condition: {getattr(condition, 'value', condition)}")

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
    """Render complete capability entries within the total character budget."""
    entries: list[str] = []

    for capability in capabilities:
        metadata = get_capability_metadata(capability)
        name = metadata["name"]
        if not name:
            continue

        description = _truncate(
            metadata["description"],
            MAX_CAPABILITY_DESCRIPTION_CHARS,
        )
        schema = get_capability_schema(capability)

        entry_lines = [
            f"Name: {name}",
            f"Description: {description or 'No description provided.'}",
        ]

        if metadata["category"]:
            entry_lines.append(f"Category: {metadata['category']}")

        entry_lines.extend(
            [
                "Input schema:",
                json.dumps(schema, ensure_ascii=False, indent=2),
            ]
        )

        if metadata["return_description"]:
            entry_lines.append(f"Returns: {metadata['return_description']}")

        if metadata["usage_notes"]:
            entry_lines.append(f"Usage notes: {metadata['usage_notes']}")

        entries.append("\n".join(entry_lines))

    if not entries:
        return "No capabilities are available."

    rendered_entries: list[str] = []
    omitted = False

    for entry in entries:
        candidate_entries = rendered_entries + [entry]
        candidate = "\n\n".join(candidate_entries)

        # Reserve room for an omission marker when later entries may not fit.
        if len(candidate) > MAX_CAPABILITIES_CHARS:
            omitted = True
            break

        rendered_entries.append(entry)

    # If entries were omitted, make room for the marker without cutting any
    # capability entry or schema.
    if omitted:
        while rendered_entries:
            candidate = (
                "\n\n".join(rendered_entries) + "\n\n" + _CAPABILITY_OMISSION_MARKER
            )
            if len(candidate) <= MAX_CAPABILITIES_CHARS:
                return candidate
            rendered_entries.pop()

        # No complete capability entry fits alongside the marker.
        return _truncate(
            "No complete capability schema fits the configured "
            "capability context budget.",
            MAX_CAPABILITIES_CHARS,
        )

    return "\n\n".join(rendered_entries)


def _build_observations(observations: Sequence[str]) -> str:
    """Prioritize the newest observations within the total context budget."""
    recent = list(observations)[-MAX_OBSERVATION_COUNT:]

    if not recent:
        return "No previous action observations."

    # Select from newest to oldest, stopping when the budget is full.
    # Then reverse the selected entries so the prompt remains chronological.
    selected: list[str] = []

    for index in range(len(recent), 0, -1):
        observation = recent[index - 1]
        rendered = (
            observation if isinstance(observation, str) else str(observation)
        ).strip()
        rendered = _truncate(rendered, MAX_OBSERVATION_CHARS)
        line = f"{index}. {rendered or '(empty observation)'}"

        candidate = "\n".join([line, *selected])
        if len(candidate) <= MAX_OBSERVATIONS_CHARS:
            selected.insert(0, line)
            continue

        if not selected:
            # The newest observation alone is larger than the total budget.
            selected.append(_truncate(line, MAX_OBSERVATIONS_CHARS))
        break

    return "\n".join(selected) or "No previous action observations."


def _truncate(text: str, limit: int) -> str:
    """Truncate text with an explicit marker when the limit is exceeded."""
    if len(text) <= limit:
        return text

    marker = "\n...[truncated to fit context budget]"
    if limit <= len(marker):
        return marker[:limit]

    return text[: limit - len(marker)] + marker
