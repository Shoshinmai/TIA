from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tree_sitter import Language, Parser
import tree_sitter_python

from code_intelligence.models import (
    CodeParseResult,
    ParseDiagnostic,
)
from code_intelligence.symbols import extract_imports, extract_symbols


@dataclass(frozen=True, slots=True)
class LanguageAdapter:
    """Parser implementation registered for one source language."""

    language: str
    extensions: tuple[str, ...]
    parse: Callable[[str], CodeParseResult]


_PYTHON_LANGUAGE = Language(tree_sitter_python.language())


def _create_python_parser() -> Parser:
    parser = Parser()
    parser.language = _PYTHON_LANGUAGE
    return parser


def _parse_python(source: str) -> CodeParseResult:
    source_bytes = source.encode("utf-8")
    tree = _create_python_parser().parse(source_bytes)

    diagnostics: list[ParseDiagnostic] = []

    def visit(node) -> None:
        if node.type == "ERROR":
            diagnostics.append(
                ParseDiagnostic(
                    kind="syntax_error",
                    start_line=node.start_point.row + 1,
                    end_line=max(
                        node.end_point.row + 1,
                        node.start_point.row + 1,
                    ),
                    message="Tree-sitter detected invalid Python syntax.",
                )
            )

        if node.is_missing:
            diagnostics.append(
                ParseDiagnostic(
                    kind="missing_node",
                    start_line=node.start_point.row + 1,
                    end_line=max(
                        node.end_point.row + 1,
                        node.start_point.row + 1,
                    ),
                    message=f"Expected syntax node '{node.type}' is missing.",
                )
            )

        for child in node.children:
            visit(child)

    visit(tree.root_node)

    return CodeParseResult(
        language="python",
        success=not tree.root_node.has_error,
        symbols=extract_symbols(tree.root_node, source_bytes),
        imports=extract_imports(tree.root_node, source_bytes),
        diagnostics=diagnostics,
        total_lines=len(source.splitlines()),
    )


LANGUAGE_ADAPTERS: dict[str, LanguageAdapter] = {}


def register_language_adapter(adapter: LanguageAdapter) -> None:
    """Register an adapter by each of its file extensions."""
    for extension in adapter.extensions:
        normalized = extension.lower()
        if not normalized.startswith("."):
            raise ValueError(
                f"Language adapter extensions must start with '.': {extension}"
            )

        if normalized in LANGUAGE_ADAPTERS:
            raise ValueError(
                f"A language adapter is already registered for {normalized}."
            )

        LANGUAGE_ADAPTERS[normalized] = adapter


def get_language_adapter(extension: str) -> LanguageAdapter | None:
    return LANGUAGE_ADAPTERS.get(extension.lower())


register_language_adapter(
    LanguageAdapter(
        language="python",
        extensions=(".py",),
        parse=_parse_python,
    )
)

def parse_source(source: str, extension: str) -> CodeParseResult:
    """Parse source through the adapter registered for its extension."""
    adapter = get_language_adapter(extension)

    if adapter is None:
        raise ValueError("unsupported_language")

    return adapter.parse(source)