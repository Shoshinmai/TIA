import asyncio

import pytest

from tools.code_intelligence import (
    MAX_SOURCE_BYTES,
    code_intelligence,
)
from utils.location_resolver import workspace_scope


def invoke_tool(arguments: dict):
    return asyncio.run(code_intelligence.ainvoke(arguments))


def test_inspect_returns_symbols_imports_and_language(tmp_path):
    source_file = tmp_path / "agent.py"
    source_file.write_text(
        """
import os

class Agent:
    def execute(self):
        pass
""",
        encoding="utf-8",
    )

    with workspace_scope(tmp_path):
        result = invoke_tool(
            {
                "operation": "inspect",
                "path": "agent.py",
            }
        )

    assert result["success"] is True
    assert result["language"] == "python"
    assert result["total_symbols"] == 2
    assert result["total_imports"] == 1

    names = {
        symbol["qualified_name"]
        for symbol in result["symbols"]
    }

    assert names == {"Agent", "Agent.execute"}


def test_inspect_can_filter_exact_qualified_name(tmp_path):
    source_file = tmp_path / "agent.py"
    source_file.write_text(
        """
class Agent:
    def execute(self):
        pass

    def stop(self):
        pass
""",
        encoding="utf-8",
    )

    with workspace_scope(tmp_path):
        result = invoke_tool(
            {
                "operation": "inspect",
                "path": "agent.py",
                "qualified_name": "Agent.execute",
            }
        )

    assert result["success"] is True
    assert [
        symbol["qualified_name"]
        for symbol in result["symbols"]
    ] == ["Agent.execute"]

    # The total describes the whole file, not just the filtered output.
    assert result["total_symbols"] == 3


def test_read_returns_exact_symbol_source(tmp_path):
    source_file = tmp_path / "agent.py"
    source_file.write_text(
        """
class Agent:
    def execute(self):
        return True
""",
        encoding="utf-8",
    )

    with workspace_scope(tmp_path):
        result = invoke_tool(
            {
                "operation": "read",
                "path": "agent.py",
                "qualified_name": "Agent.execute",
            }
        )

    assert result["success"] is True
    assert result["qualified_name"] == "Agent.execute"
    assert "def execute(self):" in result["content"]
    assert "return True" in result["content"]


def test_read_returns_inclusive_line_range(tmp_path):
    source_file = tmp_path / "agent.py"
    source_file.write_text(
        "line one\nline two\nline three\nline four\n",
        encoding="utf-8",
    )

    with workspace_scope(tmp_path):
        result = invoke_tool(
            {
                "operation": "read",
                "path": "agent.py",
                "start_line": 2,
                "end_line": 3,
            }
        )

    assert result["success"] is True
    assert result["content"] == "line two\nline three"
    assert result["source_range"] == {
        "start_line": 2,
        "end_line": 3,
    }


def test_missing_workspace_returns_structured_error(tmp_path):
    source_file = tmp_path / "agent.py"
    source_file.write_text("pass\n", encoding="utf-8")

    result = invoke_tool(
        {
            "operation": "inspect",
            "path": str(source_file),
        }
    )

    assert result["success"] is False
    assert result["error_code"] == "workspace_unavailable"
    assert result["language"] == "unknown"


def test_path_outside_workspace_is_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.py"

    workspace.mkdir()
    outside.write_text("secret = True\n", encoding="utf-8")

    with workspace_scope(workspace):
        result = invoke_tool(
            {
                "operation": "inspect",
                "path": str(outside),
            }
        )

    assert result["success"] is False
    assert result["error_code"] == "path_outside_workspace"


def test_symlink_escape_is_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    outside = tmp_path / "outside.py"
    outside.write_text("secret = True\n", encoding="utf-8")

    link = workspace / "linked.py"

    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable in this environment.")

    with workspace_scope(workspace):
        result = invoke_tool(
            {
                "operation": "inspect",
                "path": "linked.py",
            }
        )

    assert result["success"] is False
    assert result["error_code"] == "path_outside_workspace"


def test_unsupported_extension_reports_unknown_language(tmp_path):
    source_file = tmp_path / "notes.txt"
    source_file.write_text("not Python", encoding="utf-8")

    with workspace_scope(tmp_path):
        result = invoke_tool(
            {
                "operation": "inspect",
                "path": "notes.txt",
            }
        )

    assert result["success"] is False
    assert result["error_code"] == "unsupported_language"
    assert result["language"] == "unknown"


def test_source_larger_than_limit_is_rejected(tmp_path):
    source_file = tmp_path / "large.py"
    source_file.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))

    with workspace_scope(tmp_path):
        result = invoke_tool(
            {
                "operation": "inspect",
                "path": "large.py",
            }
        )

    assert result["success"] is False
    assert result["error_code"] == "source_too_large"


def test_duplicate_qualified_name_reports_ambiguous_symbol(tmp_path):
    source_file = tmp_path / "duplicate.py"
    source_file.write_text(
        """
def execute():
    pass

def execute():
    return True
""",
        encoding="utf-8",
    )

    with workspace_scope(tmp_path):
        result = invoke_tool(
            {
                "operation": "read",
                "path": "duplicate.py",
                "qualified_name": "execute",
            }
        )

    assert result["success"] is False
    assert result["error_code"] == "ambiguous_symbol"