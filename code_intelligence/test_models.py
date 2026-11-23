import pytest
from pydantic import ValidationError

from code_intelligence.models import (
    CodeIntelligenceInput,
    SourceRange,
)


def test_source_range_accepts_inclusive_range():
    result = SourceRange(start_line=2, end_line=5)

    assert result.start_line == 2
    assert result.end_line == 5


def test_source_range_rejects_reversed_range():
    with pytest.raises(ValidationError):
        SourceRange(start_line=5, end_line=2)


def test_inspect_accepts_optional_qualified_name():
    result = CodeIntelligenceInput(
        operation="inspect",
        path="src/main.py",
        qualified_name="Agent.run",
    )

    assert result.operation == "inspect"
    assert result.qualified_name == "Agent.run"


def test_inspect_rejects_line_ranges():
    with pytest.raises(ValidationError):
        CodeIntelligenceInput(
            operation="inspect",
            path="src/main.py",
            start_line=1,
            end_line=5,
        )


def test_read_accepts_qualified_name():
    result = CodeIntelligenceInput(
        operation="read",
        path="src/main.py",
        qualified_name="Agent.run",
    )

    assert result.qualified_name == "Agent.run"


def test_read_accepts_complete_line_range():
    result = CodeIntelligenceInput(
        operation="read",
        path="src/main.py",
        start_line=3,
        end_line=8,
    )

    assert result.start_line == 3
    assert result.end_line == 8


def test_read_rejects_missing_read_target():
    with pytest.raises(ValidationError):
        CodeIntelligenceInput(
            operation="read",
            path="src/main.py",
        )


def test_read_rejects_partial_line_range():
    with pytest.raises(ValidationError):
        CodeIntelligenceInput(
            operation="read",
            path="src/main.py",
            start_line=1,
        )


def test_read_rejects_qualified_name_and_line_range_together():
    with pytest.raises(ValidationError):
        CodeIntelligenceInput(
            operation="read",
            path="src/main.py",
            qualified_name="Agent.run",
            start_line=1,
            end_line=5,
        )


def test_read_rejects_reversed_line_range():
    with pytest.raises(ValidationError):
        CodeIntelligenceInput(
            operation="read",
            path="src/main.py",
            start_line=8,
            end_line=3,
        )