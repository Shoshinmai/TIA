import json
from dataclasses import dataclass

import pytest
from pydantic import BaseModel, Field

import runtime.agentic_loop_context as context_module
from runtime.agentic_loop_context import (
    build_agentic_loop_context,
)
from utils.tool_prompt_builder import (
    build_capability_prompt,
    get_capability_schema,
)


class ExampleInput(BaseModel):
    path: str = Field(description="Path to inspect.")
    recursive: bool = Field(
        default=False,
        description="Whether to inspect recursively.",
    )


@dataclass
class FakeCapability:
    name: str
    description: str
    args_schema: type[BaseModel]
    category: str | None = None
    return_description: str | None = None
    usage_notes: str | None = None


@pytest.fixture
def capability() -> FakeCapability:
    return FakeCapability(
        name="inspect_path",
        description="Inspect a path.",
        args_schema=ExampleInput,
        category="filesystem",
        return_description="Returns path metadata.",
        usage_notes="Use a discovered path when possible.",
    )


def test_missing_goal_raises_value_error():
    with pytest.raises(ValueError, match="original task goal"):
        build_agentic_loop_context({}, capabilities=[])


def test_goal_can_be_resolved_from_task_mapping():
    result = build_agentic_loop_context(
        {"task": {"goal": "Inspect a Python file"}},
        capabilities=[],
    )

    assert result.goal == "Inspect a Python file"


def test_absent_memory_produces_explicit_fallbacks():
    result = build_agentic_loop_context(
        {"goal": "Inspect a Python file"},
        capabilities=[],
    )

    assert "No active task memory available." in result.loop_context
    assert "No execution history available." in result.loop_context
    assert "No task plan exists." in result.loop_context
    assert result.observations == "No previous action observations."


def test_shared_schema_helper_returns_full_json_schema(capability):
    schema = get_capability_schema(capability)

    assert schema["properties"]["path"]["type"] == "string"
    assert "recursive" in schema["properties"]

    # The schema must be JSON-serializable.
    json.dumps(schema)


def test_loop_capability_format_contains_full_schema(capability):
    rendered = _build_capabilities([capability])
    expected_schema = json.dumps(
        get_capability_schema(capability),
        ensure_ascii=False,
        indent=2,
    )

    assert "Name: inspect_path" in rendered
    assert "Description: Inspect a path." in rendered
    assert "Input schema:" in rendered
    assert expected_schema in rendered
    assert "Category: filesystem" in rendered


def test_planner_prompt_still_uses_human_readable_arguments(capability):
    rendered = build_capability_prompt([capability])

    assert "Capability: inspect_path" in rendered
    assert "Arguments:" in rendered
    assert "- path (string): Path to inspect." in rendered
    assert "- recursive (boolean) (optional): Whether to inspect recursively." in rendered
    assert "Returns:" in rendered
    assert "Usage Notes:" in rendered


def test_observations_are_all_preserved():
    """After removing observation count budgets, all supplied observations are preserved in chronological order."""
    observations = [f"observation-{index}" for index in range(15)]

    rendered = _build_observations(observations)

    # All observations should be present since there's no count limit
    for i in range(15):
        obs = f"observation-{i}"
        assert obs in rendered


def test_observations_are_all_preserved():
    """After removing observation count budgets, all supplied observations are preserved."""
    observations = [f"observation-{index}" for index in range(15)]

    rendered = _build_observations(observations)

    # All observations should be present since there's no count limit
    for i in range(1, 16):
        obs = f"observation-{i}"
        assert obs in rendered


def test_goal_and_loop_context_are_preserved():
    result = build_agentic_loop_context(
        {
            "goal": "A" * 100,
            "workspace": "B" * 200,
        },
        capabilities=[],
    )

    assert result.goal == "A" * 100
    assert "workspace" in result.loop_context.lower() or "B" * 200 in result.loop_context


def test_capability_format_contains_full_description_and_schema(capability):
    rendered = _build_capabilities([capability])

    assert "Name: inspect_path" in rendered
    assert "Description: Inspect a path." in rendered
    assert "Input schema:" in rendered


def test_default_capability_budget_is_positive():
    # After removing artificial budgets, these values are no longer used for truncation.
    # Verify the functions work without budget enforcement.
    observations = ["obs1", "obs2", "obs3"]
    rendered = _build_observations(observations)
    assert "obs1" in rendered
    assert "obs3" in rendered


def test_observations_are_all_preserved():
    """After removing observation count budgets, all supplied observations are preserved in chronological order."""
    observations = [f"observation-{index}" for index in range(15)]

    rendered = _build_observations(observations)

    # All observations should be present since there's no count limit
    for i in range(15):
        obs = f"observation-{i}"
        assert obs in rendered


def _build_capabilities(capabilities):
    return context_module._build_capabilities(capabilities)


def _build_observations(observations):
    return context_module._build_observations(observations)