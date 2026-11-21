from __future__ import annotations

from tree_sitter import Language, Parser
import tree_sitter_python

from code_intelligence.models import (
    ParseDiagnostic,
    PythonParseResult,
)


_PYTHON_LANGUAGE = Language(tree_sitter_python.language())


def create_python_parser() -> Parser:
    """Create an independent Tree-sitter Python parser."""

    parser = Parser()
    parser.language = _PYTHON_LANGUAGE
    return parser


def parse_python_source(source: str) -> PythonParseResult:
    """Parse Python source and report syntax diagnostics.

    Tree-sitter can produce a partial syntax tree for invalid source.
    We preserve that tree's valid structural information and return
    diagnostics instead of treating every syntax error as a parser crash.
    """

    source_bytes = source.encode("utf-8")
    parser = create_python_parser()
    tree = parser.parse(source_bytes)

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

        elif node.is_missing:
            diagnostics.append(
                ParseDiagnostic(
                    kind="missing_node",
                    start_line=node.start_point.row + 1,
                    end_line=node.start_point.row + 1,
                    message=(
                        f"Expected syntax node '{node.type}' is missing."
                    ),
                )
            )

        for child in node.children:
            visit(child)

    visit(tree.root_node)

    return PythonParseResult(
        success=not tree.root_node.has_error,
        diagnostics=diagnostics,
        total_lines=len(source.splitlines()),
    )