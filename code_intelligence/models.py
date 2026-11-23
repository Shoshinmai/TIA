from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


CodeSymbolKind = Literal["class", "function", "method"]
CodeImportKind = Literal["import", "from_import"]
CodeOperation = Literal["inspect", "read"]


class SourceRange(BaseModel):
    """One-based, inclusive source line range."""

    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> "SourceRange":
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class CodeSymbol(BaseModel):
    """A structural definition discovered in a source file."""

    name: str
    qualified_name: str
    kind: str
    source_range: SourceRange
    parent: str | None = None
    docstring: str | None = None
    decorators: list[str] = Field(default_factory=list)
    is_async: bool = False


class CodeImport(BaseModel):
    """An import statement preserved from the source file."""

    kind: str
    statement: str
    source_range: SourceRange


class ParseDiagnostic(BaseModel):
    """A syntax diagnostic reported by the language parser."""

    kind: Literal["syntax_error", "missing_node"]
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    message: str


class CodeParseResult(BaseModel):
    """Language-neutral output from a language adapter."""

    language: str
    success: bool
    symbols: list[CodeSymbol] = Field(default_factory=list)
    imports: list[CodeImport] = Field(default_factory=list)
    diagnostics: list[ParseDiagnostic] = Field(default_factory=list)
    total_lines: int = Field(ge=0)


class CodeInspectionResult(BaseModel):
    """Public result contract for structural inspection."""

    success: bool
    path: str
    language: str
    symbols: list[CodeSymbol] = Field(default_factory=list)
    imports: list[CodeImport] = Field(default_factory=list)
    diagnostics: list[ParseDiagnostic] = Field(default_factory=list)
    total_symbols: int = Field(default=0, ge=0)
    total_imports: int = Field(default=0, ge=0)
    total_lines: int = Field(default=0, ge=0)
    error_code: str | None = None
    error: str | None = None


class CodeReadResult(BaseModel):
    """Public result contract for source retrieval."""

    success: bool
    path: str
    language: str
    content: str | None = None
    source_range: SourceRange | None = None
    qualified_name: str | None = None
    error_code: str | None = None
    error: str | None = None


class CodeIntelligenceInput(BaseModel):
    """Unified input contract for code inspection and source retrieval."""

    operation: CodeOperation = Field(
        description=(
            "'inspect' returns structural information; "
            "'read' retrieves source code."
        ),
    )
    path: str = Field(
        min_length=1,
        description=(
            "Source file path relative to the project workspace, "
            "or an absolute path inside that workspace."
        ),
    )
    qualified_name: str | None = Field(
        default=None,
        description=(
            "Exact qualified symbol name, such as 'Agent.run'. "
            "For inspect, this optionally filters the returned symbols. "
            "For read, it retrieves that symbol's source."
        ),
    )
    start_line: int | None = Field(
        default=None,
        ge=1,
        description="First line of a one-based inclusive range for read.",
    )
    end_line: int | None = Field(
        default=None,
        ge=1,
        description="Last line of a one-based inclusive range for read.",
    )

    @model_validator(mode="after")
    def validate_operation_arguments(self) -> "CodeIntelligenceInput":
        has_start = self.start_line is not None
        has_end = self.end_line is not None

        if self.operation == "inspect":
            if has_start or has_end:
                raise ValueError(
                    "Line ranges are only supported by operation='read'."
                )
            return self

        if self.qualified_name and (has_start or has_end):
            raise ValueError(
                "For operation='read', use qualified_name or a line range, "
                "not both."
            )

        if has_start != has_end:
            raise ValueError(
                "For operation='read', provide both start_line and end_line."
            )

        if not self.qualified_name and not has_start:
            raise ValueError(
                "For operation='read', provide qualified_name or "
                "both start_line and end_line."
            )

        if has_start and self.end_line < self.start_line:  # pyright: ignore[reportOperatorIssue]
            raise ValueError("end_line must be >= start_line")

        return self
