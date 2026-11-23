
from __future__ import annotations

import asyncio
import tokenize
from pathlib import Path

from langchain_core.tools import tool

from code_intelligence.models import (
    CodeInspectionResult,
    CodeIntelligenceInput,
    CodeReadResult,
    SourceRange,
)
from code_intelligence.parser import (
    get_language_adapter,
    parse_source,
)
from code_intelligence.symbols import resolve_symbol
from utils.location_resolver import (
    get_workspace_root,
    resolve_location,
)


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_LINES = 1000


def _resolve_code_file(path: str) -> tuple[Path, str]:
    """Resolve a source file and enforce workspace containment."""
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

    adapter = get_language_adapter(resolved.suffix)
    if adapter is None:
        raise ValueError("unsupported_language")

    if resolved.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("source_too_large")

    return resolved, adapter.language


def _read_source(path: Path, language: str) -> str:
    """Read source using the language's expected source encoding."""
    if language == "python":
        with tokenize.open(path) as source_file:
            return source_file.read()

    return path.read_text(encoding="utf-8-sig")


def _error_code(error: Exception) -> str:
    known_codes = {
        "workspace_unavailable",
        "path_outside_workspace",
        "not_a_file",
        "unsupported_language",
        "source_too_large",
        "symbol_not_found",
        "invalid_source_range",
        "invalid_read_request",
    }

    message = str(error)
    if message in known_codes:
        return message

    if isinstance(error, UnicodeError):
        return "source_decode_error"

    return "io_error"


def _error_result(
    *,
    operation: str,
    path: str,
    language: str,
    error: Exception,
) -> dict:
    code = _error_code(error)

    if operation == "inspect":
        return CodeInspectionResult(
            success=False,
            path=path,
            language=language,
            error_code=code,
            error=str(error),
        ).model_dump(mode="json")

    return CodeReadResult(
        success=False,
        path=path,
        language=language,
        error_code=code,
        error=str(error),
    ).model_dump(mode="json")


def _inspect(
    *,
    path: str,
    language: str,
    source: str,
    qualified_name: str | None,
) -> dict:
    parsed = parse_source(source, Path(path).suffix)

    symbols = parsed.symbols
    if qualified_name:
        symbol = resolve_symbol(symbols, qualified_name)
        if symbol is None:
            raise ValueError("symbol_not_found")
        symbols = [symbol]

    return CodeInspectionResult(
        success=parsed.success,
        path=path,
        language=parsed.language,
        symbols=symbols,
        imports=parsed.imports,
        diagnostics=parsed.diagnostics,
        total_symbols=len(parsed.symbols),
        total_imports=len(parsed.imports),
        total_lines=parsed.total_lines,
    ).model_dump(mode="json")


def _read(
    *,
    path: str,
    language: str,
    source: str,
    qualified_name: str | None,
    start_line: int | None,
    end_line: int | None,
) -> dict:
    lines = source.splitlines()

    if qualified_name:
        parsed = parse_source(source, Path(path).suffix)
        symbol = resolve_symbol(parsed.symbols, qualified_name)

        if symbol is None:
            raise ValueError("symbol_not_found")

        selected_range = symbol.source_range

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

    selected_line_count = (
        selected_range.end_line - selected_range.start_line + 1
    )

    if selected_line_count > MAX_SOURCE_LINES:
        raise ValueError("invalid_source_range")

    content = "\n".join(
        lines[
            selected_range.start_line - 1:
            selected_range.end_line
        ]
    )

    return CodeReadResult(
        success=True,
        path=path,
        language=language,
        content=content,
        source_range=selected_range,
        qualified_name=qualified_name,
    ).model_dump(mode="json")


def _execute_code_intelligence(
    *,
    operation: str,
    path: str,
    qualified_name: str | None,
    start_line: int | None,
    end_line: int | None,
) -> dict:
    language = Path(path).suffix.lower().lstrip(".") or "unknown"

    try:
        resolved, language = _resolve_code_file(path)
        source = _read_source(resolved, language)
        resolved_path = str(resolved)

        if operation == "inspect":
            return _inspect(
                path=resolved_path,
                language=language,
                source=source,
                qualified_name=qualified_name,
            )

        return _read(
            path=resolved_path,
            language=language,
            source=source,
            qualified_name=qualified_name,
            start_line=start_line,
            end_line=end_line,
        )

    except (OSError, ValueError) as exc:
        return _error_result(
            operation=operation,
            path=path,
            language=language,
            error=exc,
        )


@tool(args_schema=CodeIntelligenceInput)
async def code_intelligence(
    operation: str,
    path: str,
    qualified_name: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    """
    Inspect source structure or retrieve source code.

    Use operation='inspect' to retrieve symbols, imports, source ranges,
    decorators, docstrings and syntax diagnostics.

    Use operation='read' with qualified_name to retrieve a symbol, or
    with start_line and end_line to retrieve an inclusive line range.

    Paths must resolve to files inside the active project workspace.
    """
    return await asyncio.to_thread(
        _execute_code_intelligence,
        operation=operation,
        path=path,
        qualified_name=qualified_name,
        start_line=start_line,
        end_line=end_line,
    )