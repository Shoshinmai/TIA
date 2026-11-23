
from __future__ import annotations

import ast

from tree_sitter import Node

from code_intelligence.models import (
    CodeImport,
    CodeSymbol,
    SourceRange,
)


DEFINITION_TYPES = {
    "class_definition": "class",
    "function_definition": "function",
}


def _node_text(source: bytes, node: Node | None) -> str | None:
    if node is None:
        return None

    return source[node.start_byte:node.end_byte].decode(
        "utf-8",
        errors="strict",
    )


def _field(node: Node, name: str) -> Node | None:
    return node.child_by_field_name(name)


def _source_range(node: Node) -> SourceRange:
    return SourceRange(
        start_line=node.start_point.row + 1,
        end_line=max(
            node.end_point.row + 1,
            node.start_point.row + 1,
        ),
    )


def _definition_node(node: Node) -> tuple[Node, Node | None]:
    """Return the underlying definition and its decorator wrapper."""
    if node.type == "decorated_definition":
        definition = next(
            (
                child
                for child in node.named_children
                if child.type in DEFINITION_TYPES
            ),
            None,
        )
        if definition is not None:
            return definition, node

    return node, None


def _definition_name(node: Node, source: bytes) -> str | None:
    return _node_text(source, _field(node, "name"))


def _docstring(node: Node, source: bytes) -> str | None:
    body = _field(node, "body")

    if body is None or not body.named_children:
        return None

    first_statement = body.named_children[0]

    if first_statement.type != "expression_statement":
        return None

    if not first_statement.named_children:
        return None

    expression = first_statement.named_children[0]

    if expression.type != "string":
        return None

    raw_value = _node_text(source, expression)
    if raw_value is None:
        return None

    try:
        value = ast.literal_eval(raw_value)
    except (SyntaxError, ValueError):
        return raw_value

    return value if isinstance(value, str) else raw_value


def _decorators(
    wrapper: Node | None,
    source: bytes,
) -> list[str]:
    if wrapper is None:
        return []

    return [
        text
        for child in wrapper.named_children
        if child.type == "decorator"
        and (text := _node_text(source, child)) is not None
    ]


def _is_async(node: Node) -> bool:
    return any(child.type == "async" for child in node.children)


def extract_symbols(root: Node, source: bytes) -> list[CodeSymbol]:
    """Extract definitions once, preserving lexical nesting.

    A function is classified as a method only when its immediate
    containing scope is a class. Nested functions inside methods remain
    functions.
    """
    symbols: list[CodeSymbol] = []

    def visit(
        node: Node,
        parent_qualified_name: str | None = None,
        parent_scope_kind: str | None = None,
    ) -> None:
        definition, wrapper = _definition_node(node)

        if definition.type in DEFINITION_TYPES:
            name = _definition_name(definition, source)

            if name:
                base_kind = DEFINITION_TYPES[definition.type]
                kind = (
                    "method"
                    if base_kind == "function"
                    and parent_scope_kind == "class"
                    else base_kind
                )

                qualified_name = (
                    f"{parent_qualified_name}.{name}"
                    if parent_qualified_name
                    else name
                )

                symbols.append(
                    CodeSymbol(
                        name=name,
                        qualified_name=qualified_name,
                        kind=kind,  # pyright: ignore[reportArgumentType]
                        source_range=_source_range(wrapper or definition),
                        parent=parent_qualified_name,
                        docstring=_docstring(definition, source),
                        decorators=_decorators(wrapper, source),
                        is_async=_is_async(definition),
                    )
                )

                body = _field(definition, "body")
                if body is not None:
                    for child in body.named_children:
                        visit(
                            child,
                            qualified_name,
                            base_kind,
                        )
                return

        for child in node.named_children:
            visit(
                child,
                parent_qualified_name,
                parent_scope_kind,
            )

    visit(root)
    return symbols


def extract_imports(root: Node, source: bytes) -> list[CodeImport]:
    """Extract Python import statements without losing their source form."""
    imports: list[CodeImport] = []

    def visit(node: Node) -> None:
        if node.type == "import_statement":
            imports.append(
                CodeImport(
                    kind="import",
                    statement=_node_text(source, node) or "",
                    source_range=_source_range(node),
                )
            )
            return

        if node.type == "import_from_statement":
            imports.append(
                CodeImport(
                    kind="from_import",
                    statement=_node_text(source, node) or "",
                    source_range=_source_range(node),
                )
            )
            return

        for child in node.named_children:
            visit(child)

    visit(root)
    return imports

class AmbiguousSymbolError(ValueError):
    """Raised when an exact qualified name resolves to multiple symbols."""

def resolve_symbol(
    symbols: list[CodeSymbol],
    qualified_name: str,
) -> CodeSymbol | None:
    """Resolve an exact qualified name.

    Returns None when no symbol matches and raises AmbiguousSymbolError
    when multiple definitions share the same qualified name.
    """
    matches = [
        symbol
        for symbol in symbols
        if symbol.qualified_name == qualified_name
    ]

    if not matches:
        return None

    if len(matches) > 1:
        raise AmbiguousSymbolError(
            f"Multiple symbols match qualified name: {qualified_name}"
        )

    return matches[0]