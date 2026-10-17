
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel


def get_capability_schema(capability: Any) -> dict[str, Any]:
    """Return a JSON-compatible schema for a capability's arguments.

    Supports the Pydantic schema classes used by LangChain tools, Pydantic
    model instances, and dictionary schemas. Returns an empty dictionary when
    the schema is unavailable or cannot be serialized.
    """
    schema_source = getattr(capability, "args_schema", None)

    if schema_source is None:
        return {}

    try:
        if isinstance(schema_source, type) and issubclass(
            schema_source, BaseModel
        ):
            schema = schema_source.model_json_schema()
        elif isinstance(schema_source, BaseModel):
            schema = schema_source.__class__.model_json_schema()
        elif isinstance(schema_source, dict):
            schema = schema_source
        else:
            return {}

        # Normalize the result to JSON-compatible data.
        return json.loads(json.dumps(schema, ensure_ascii=False))

    except (AttributeError, TypeError, ValueError):
        return {}


def get_capability_metadata(capability: Any) -> dict[str, str]:
    """Extract display metadata shared by capability prompt builders."""
    name = getattr(capability, "name", "")
    description = getattr(capability, "description", "")
    category = getattr(capability, "category", None)
    return_description = getattr(capability, "return_description", None)
    usage_notes = getattr(capability, "usage_notes", None)

    return {
        "name": name.strip() if isinstance(name, str) else "",
        "description": (
            description.strip() if isinstance(description, str) else ""
        ),
        "category": category.strip() if isinstance(category, str) else "",
        "return_description": (
            return_description.strip()
            if isinstance(return_description, str)
            else ""
        ),
        "usage_notes": (
            usage_notes.strip() if isinstance(usage_notes, str) else ""
        ),
    }


def build_capability_prompt(tools: list[BaseTool]) -> str:
    """Build the existing human-readable capability reference for the Planner.

    Keep this format compatible with the Planner's current prompt contract.
    The autonomous loop uses the shared schema/metadata helpers but renders
    the input schema as JSON instead.
    """
    sections: list[str] = []

    for tool in tools:
        metadata = get_capability_metadata(tool)
        if not metadata["name"]:
            continue

        schema = get_capability_schema(tool)
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        section: list[str] = [
            "=" * 70,
            f"Capability: {metadata['name']}",
            "=" * 70,
            "",
        ]

        if metadata["category"]:
            section.extend(
                [
                    f"Category: {metadata['category']}",
                    "",
                ]
            )

        section.extend(
            [
                "Description:",
                metadata["description"],
                "",
                "Arguments:",
            ]
        )

        if not properties:
            section.append("- None")
        else:
            for arg_name, info in properties.items():
                if not isinstance(info, dict):
                    info = {}

                arg_type = info.get("type", "any")
                optional = (
                    "" if arg_name in required else " (optional)"
                )
                description = info.get("description", "")

                line = f"- {arg_name} ({arg_type}){optional}"
                if description:
                    line += f": {description}"

                section.append(line)

        if metadata["return_description"]:
            section.extend(
                [
                    "",
                    "Returns:",
                    metadata["return_description"],
                ]
            )

        if metadata["usage_notes"]:
            section.extend(
                [
                    "",
                    "Usage Notes:",
                    metadata["usage_notes"],
                ]
            )

        sections.append("\n".join(section))

    return "\n\n" + "-" * 70 + "\n\n".join(sections)
