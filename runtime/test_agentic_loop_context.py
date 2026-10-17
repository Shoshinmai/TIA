
import json
from dataclasses import dataclass

import pytest
from pydantic import BaseModel, Field

import runtime.agentic_loop_context as context_module
from runtime.agentic_loop_context import (
    MAX_CAPABILITIES_CHARS,
    MAX_GOAL_CHARS,
    MAX_LOOP_CONTEXT_CHARS,
    MAX_OBSERVATION_CHARS,
    MAX_OBSERVATION_COUNT,
    MAX_OBSERVATIONS_CHARS,
    _build_capabilities,
    _build_observations,
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
    print(result)

    assert result.goal == "Inspect a Python file"


def test_absent_memory_produces_explicit_fallbacks():
    result = build_agentic_loop_context(
        {"goal": "Inspect a Python file"},
        capabilities=[],
    )

    print(result)
    assert "No active task memory available." in result.loop_context
    assert "No execution history available." in result.loop_context
    assert "No task plan exists." in result.loop_context
    assert result.observations == "No previous action observations."


def test_shared_schema_helper_returns_full_json_schema(capability):
    schema = get_capability_schema(capability)
    print(json.dumps(schema, indent=2, ensure_ascii=False))

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
    print(rendered)

    assert "Name: inspect_path" in rendered
    assert "Description: Inspect a path." in rendered
    assert "Input schema:" in rendered
    assert expected_schema in rendered
    assert "Category: filesystem" in rendered


def test_planner_prompt_still_uses_human_readable_arguments(capability):
    rendered = build_capability_prompt([capability])
    print(rendered)

    assert "Capability: inspect_path" in rendered
    assert "Arguments:" in rendered
    assert "- path (string): Path to inspect." in rendered
    assert "- recursive (boolean) (optional): Whether to inspect recursively." in rendered
    assert "Returns:" in rendered
    assert "Usage Notes:" in rendered


def test_observation_count_keeps_only_newest_entries():
    observations = [f"observation-{index}" for index in range(15)]

    rendered = _build_observations(observations)
    print(rendered)

    assert "observation-4" not in rendered
    assert "observation-5" in rendered
    assert "observation-14" in rendered

def test_observation_and_total_limits_are_enforced():
    observations = ["x" * (MAX_OBSERVATION_CHARS * 2)] * 10

    rendered = _build_observations(observations)
    print(rendered)

    assert len(rendered) <= MAX_OBSERVATIONS_CHARS
    assert "truncated to fit context budget" in rendered


def test_goal_and_loop_context_limits_are_enforced(monkeypatch):
    monkeypatch.setattr(context_module, "MAX_GOAL_CHARS", 32)
    monkeypatch.setattr(context_module, "MAX_LOOP_CONTEXT_CHARS", 64)

    result = build_agentic_loop_context(
        {
            "goal": "A" * 100,
            "workspace": "B" * 200,
        },
        capabilities=[],
    )
    print(result)

    assert len(result.goal) <= 32
    assert len(result.loop_context) <= 64


def test_capability_budget_never_returns_a_partial_schema(
    capability,
    monkeypatch,
):
    full_entry = _build_capabilities([capability])
    schema = json.dumps(
        get_capability_schema(capability),
        ensure_ascii=False,
        indent=2,
    )

    # Force the complete entry not to fit.
    monkeypatch.setattr(
        context_module,
        "MAX_CAPABILITIES_CHARS",
        len(full_entry) - 1,
    )

    rendered = _build_capabilities([capability])

    assert len(rendered) <= len(full_entry) - 1
    assert schema not in rendered
    assert "No complete capability schema fits" in rendered


def test_capability_total_budget_is_enforced(capability, monkeypatch):
    second = FakeCapability(
        name="another_capability",
        description="Another capability.",
        args_schema=ExampleInput,
    )

    monkeypatch.setattr(context_module, "MAX_CAPABILITIES_CHARS", 500)

    rendered = _build_capabilities([capability, second])

    assert len(rendered) <= 500
    assert (
        "omitted because their complete descriptions and schemas"
        in rendered
        or "No complete capability schema fits" in rendered
    )


def test_default_capability_budget_is_positive():
    assert MAX_CAPABILITIES_CHARS > 0
    assert MAX_GOAL_CHARS > 0
    assert MAX_LOOP_CONTEXT_CHARS > 0
    assert MAX_OBSERVATION_COUNT > 0
