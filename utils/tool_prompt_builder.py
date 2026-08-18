from typing import Any

from langchain_core.tools import BaseTool


def build_capability_prompt(tools: list[BaseTool]) -> str:
    """
    Build a planner-friendly capability reference from the
    registered LangChain tools.

    This information is intended ONLY for the Planner node.
    """

    sections: list[str] = []

    for tool in tools:

        schema = tool.args_schema.model_json_schema()

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        section = []

        section.append("=" * 70)
        section.append(f"Capability: {tool.name}")
        section.append("=" * 70)
        section.append("")
        
        category = getattr(tool, "category", None)

        if category:
            section.append(f"Category: {category}")
            section.append("")
        section.append("Description:")
        section.append(tool.description.strip())
        section.append("")

        section.append("Arguments:")

        if not properties:
            section.append("- None")

        else:

            for arg_name, info in properties.items():

                arg_type = info.get("type", "any")

                optional = "" if arg_name in required else " (optional)"

                description = info.get("description", "")

                line = f"- {arg_name} ({arg_type}){optional}"

                if description:
                    line += f": {description}"

                section.append(line)

        # -----------------------------
        # Return Information
        # -----------------------------

        return_info = getattr(tool, "return_description", None)

        if return_info:

            section.append("")
            section.append("Returns:")
            section.append(return_info)

        # -----------------------------
        # Usage Notes
        # -----------------------------

        usage_notes = getattr(tool, "usage_notes", None)

        if usage_notes:

            section.append("")
            section.append("Usage Notes:")
            section.append(usage_notes)

        sections.append("\n".join(section))

    return "\n\n" + "-" * 70 + "\n\n".join(sections)