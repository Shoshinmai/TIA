from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceRange(BaseModel):
    """One-based, inclusive source line range."""

    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class CodeSymbol(BaseModel):
    """A structural symbol discovered in a Python source file."""

    name: str
    qualified_name: str
    kind: Literal["class", "function", "method"]
    source_range: SourceRange
    parent: str | None = None
    docstring: str | None = None
    decorators: list[str] = Field(default_factory=list)
    is_async: bool = False


class ParseDiagnostic(BaseModel):
    """A syntax diagnostic reported by Tree-sitter."""

    kind: Literal["syntax_error", "missing_node"]
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    message: str


class PythonParseResult(BaseModel):
    """Parsed Python source and its structural symbols."""

    success: bool
    symbols: list[CodeSymbol] = Field(default_factory=list)
    diagnostics: list[ParseDiagnostic] = Field(default_factory=list)
    total_lines: int = Field(ge=0)


class CodeInspectionResult(BaseModel):
    """Public result contract for structural inspection."""

    success: bool
    path: str
    language: Literal["python"] = "python"
    symbols: list[CodeSymbol] = Field(default_factory=list)
    diagnostics: list[ParseDiagnostic] = Field(default_factory=list)
    total_symbols: int = Field(default=0, ge=0)
    total_lines: int = Field(default=0, ge=0)
    error_code: str | None = None
    error: str | None = None


class CodeReadResult(BaseModel):
    """Public result contract for source retrieval."""

    success: bool
    path: str
    content: str | None = None
    source_range: SourceRange | None = None
    qualified_name: str | None = None
    error_code: str | None = None
    error: str | None = None

class CodeInspectionInput(BaseModel):
    """Input for inspecting Python source structure."""

    path: str = Field(
        min_length=1,
        description=(
            "Python file path relative to the project workspace, "
            "or an absolute path inside that workspace."
        ),
    )

    qualified_name: str | None = Field(
        default=None,
        description=(
            "Optional exact qualified symbol name. When omitted, "
            "return the complete structural outline."
        ),
    )


class CodeReadingInput(BaseModel):
    """Input for retrieving a specific Python source region."""

    path: str = Field(
        min_length=1,
        description="Python source file inside the project workspace.",
    )

    qualified_name: str | None = Field(
        default=None,
        description=(
            "Exact qualified symbol to retrieve, for example "
            "'Agent.run' or 'Agent._build_context'."
        ),
    )

    start_line: int | None = Field(
        default=None,
        ge=1,
        description="First line of a one-based inclusive source range.",
    )

    end_line: int | None = Field(
        default=None,
        ge=1,
        description="Last line of a one-based inclusive source range.",
    )