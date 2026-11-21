from __future__ import annotations

import asyncio
import tokenize
from pathlib import Path

from langchain_core.tools import tool

from code_intelligence.models import (
    CodeInspectionInput,
    CodeReadingInput,
    CodeInspectionResult,
    CodeReadResult,
    SourceRange,
)
from code_intelligence.parser import parse_python_source
from code_intelligence.symbols import resolve_symbol
from utils.location_resolver import (
    get_workspace_root,
    resolve_location,
)


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_LINES = 1000


def _resolve_python_file(path: str) -> Path:
    """Resolve a Python file and enforce workspace containment."""

    workspace_root = get_workspace_root()

    if workspace_root is None:
        raise ValueError("workspace_unavailable")

    root = workspace_root.resolve(strict=True)

    resolved = resolve_location(
        path,
        current_directory=root,
        workspace_root=root,
    ).resolve(strict=True)

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("path_outside_workspace") from exc

    if not resolved.is_file():
        raise ValueError("not_a_file")

    if resolved.suffix.lower() != ".py":
        raise ValueError("unsupported_language")

    if resolved.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("source_too_large")

    return resolved


def _read_python_source(path: Path) -> str:
    """Read Python source while respecting Python encoding declarations."""

    with tokenize.open(path) as source_file:
        return source_file.read()


def _error_result(
    *,
    path: str,
    error: Exception,
    inspection: bool,
) -> dict:
    error_code = str(error)

    if error_code not in {
        "workspace_unavailable",
        "path_outside_workspace",
        "not_a_file",
        "unsupported_language",
        "source_too_large",
        "symbol_not_found",
        "ambiguous_symbol",
        "invalid_source_range",
        "invalid_read_request",
    }:
        error_code = "io_error"

    if inspection:
        return CodeInspectionResult(
            success=False,
            path=path,
            error_code=error_code,
            error=str(error),
        ).model_dump(mode="json")

    return CodeReadResult(
        success=False,
        path=path,
        error_code=error_code,
        error=str(error),
    ).model_dump(mode="json")


def _inspect_python_code_sync(
    path: str,
    qualified_name: str | None = None,
) -> dict:
    try:
        resolved = _resolve_python_file(path)
        source = _read_python_source(resolved)
        parsed = parse_python_source(source)

        symbols = parsed.symbols

        if qualified_name:
            matches = [
                symbol
                for symbol in symbols
                if symbol.qualified_name == qualified_name
            ]

            if not matches:
                raise ValueError("symbol_not_found")

            if len(matches) > 1:
                raise ValueError("ambiguous_symbol")

            symbols = matches

        return CodeInspectionResult(
            success=parsed.success,
            path=str(resolved),
            symbols=symbols,
            diagnostics=parsed.diagnostics,
            total_symbols=len(parsed.symbols),
            total_lines=parsed.total_lines,
        ).model_dump(mode="json")

    except (OSError, ValueError) as exc:
        return _error_result(
            path=path,
            error=exc,
            inspection=True,
        )


@tool(args_schema=CodeInspectionInput)
async def inspect_python_code(
    path: str,
    qualified_name: str | None = None,
) -> dict:
    """
    Inspect the structure of a Python source file.

    Returns classes, functions, methods, qualified names,
    source ranges, decorators, docstrings, and syntax diagnostics.

    When qualified_name is supplied, returns only that exact symbol.
    """

    return await asyncio.to_thread(
        _inspect_python_code_sync,
        path,
        qualified_name,
    )


def _read_python_code_sync(
    path: str,
    qualified_name: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    try:
        if qualified_name and (
            start_line is not None or end_line is not None
        ):
            raise ValueError("invalid_read_request")

        if not qualified_name and (
            start_line is None or end_line is None
        ):
            raise ValueError("invalid_read_request")

        resolved = _resolve_python_file(path)
        source = _read_python_source(resolved)
        lines = source.splitlines()

        selected_range: SourceRange

        if qualified_name:
            parsed = parse_python_source(source)

            matches = [
                symbol
                for symbol in parsed.symbols
                if symbol.qualified_name == qualified_name
            ]

            if not matches:
                raise ValueError("symbol_not_found")

            if len(matches) > 1:
                raise ValueError("ambiguous_symbol")

            selected_range = matches[0].source_range

        else:
            if (
                start_line is None
                or end_line is None
                or end_line < start_line
                or end_line > len(lines)
            ):
                raise ValueError("invalid_source_range")

            selected_range = SourceRange(
                start_line=start_line,
                end_line=end_line,
            )

        if (
            selected_range.end_line - selected_range.start_line + 1
            > MAX_SOURCE_LINES
        ):
            raise ValueError("invalid_source_range")

        content = "\n".join(
            lines[
                selected_range.start_line - 1:
                selected_range.end_line
            ]
        )

        return CodeReadResult(
            success=True,
            path=str(resolved),
            content=content,
            source_range=selected_range,
            qualified_name=qualified_name,
        ).model_dump(mode="json")

    except (OSError, ValueError) as exc:
        return _error_result(
            path=path,
            error=exc,
            inspection=False,
        )


@tool(args_schema=CodeReadingInput)
async def read_python_code(
    path: str,
    qualified_name: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    """
    Retrieve source code by exact qualified symbol or line range.

    Supply either qualified_name or both start_line and end_line.
    Line ranges are one-based and inclusive.
    """

    return await asyncio.to_thread(
        _read_python_code_sync,
        path,
        qualified_name,
        start_line,
        end_line,
    )