from __future__ import annotations

from tree_sitter import Node

from code_intelligence.models import (
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


def _direct_child(
    node: Node,
    child_type: str,
) -> Node | None:
    for child in node.named_children:
        if child.type == child_type:
            return child

    return None


def _definition_name(
    node: Node,
    source: bytes,
) -> str | None:
    name_node = _direct_child(node, "identifier")
    return _node_text(source, name_node)


def _decorators(
    node: Node,
    source: bytes,
) -> list[str]:
    decorators: list[str] = []

    for child in node.children:
        if child.type == "decorated_definition":
            continue

        if child.type == "decorator":
            text = _node_text(source, child)
            if text:
                decorators.append(text)

    return decorators


def _docstring(
    node: Node,
    source: bytes,
) -> str | None:
    body = _direct_child(node, "block")

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

    return _node_text(source, expression)


def _source_range(node: Node) -> SourceRange:
    return SourceRange(
        start_line=node.start_point.row + 1,
        end_line=max(
            node.end_point.row + 1,
            node.start_point.row + 1,
        ),
    )


def extract_symbols(
    root: Node,
    source: bytes,
) -> list[CodeSymbol]:
    """Extract definitions in source order.

    Qualified names use dotted nesting:
        module_function
        OuterClass
        OuterClass.method
        OuterClass.InnerClass
        OuterClass.InnerClass.method
    """

    symbols: list[CodeSymbol] = []

    def visit(
        node: Node,
        parent_qualified_name: str | None = None,
        inside_class: bool = False,
    ) -> None:
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
                name = _definition_name(definition, source)

                if name:
                    kind = DEFINITION_TYPES[definition.type]

                    if kind == "function" and inside_class:
                        kind = "method"

                    qualified_name = (
                        f"{parent_qualified_name}.{name}"
                        if parent_qualified_name
                        else name
                    )

                    symbols.append(
                        CodeSymbol(
                            name=name,
                            qualified_name=qualified_name,
                            kind=kind,
                            source_range=_source_range(node),
                            parent=parent_qualified_name,
                            docstring=_docstring(definition, source),
                            decorators=[
                                text
                                for child in node.named_children
                                if child.type == "decorator"
                                and (text := _node_text(source, child))
                            ],
                            is_async=any(
                                child.type == "async"
                                for child in definition.children
                            ),
                        )
                    )

                    visit(
                        definition,
                        qualified_name,
                        kind == "class",
                    )
                    return

        elif node.type in DEFINITION_TYPES:
            name = _definition_name(node, source)

            if name:
                kind = DEFINITION_TYPES[node.type]

                if kind == "function" and inside_class:
                    kind = "method"

                qualified_name = (
                    f"{parent_qualified_name}.{name}"
                    if parent_qualified_name
                    else name
                )

                symbols.append(
                    CodeSymbol(
                        name=name,
                        qualified_name=qualified_name,
                        kind=kind,
                        source_range=_source_range(node),
                        parent=parent_qualified_name,
                        docstring=_docstring(node, source),
                        is_async=any(
                            child.type == "async"
                            for child in node.children
                        ),
                    )
                )

                body = _direct_child(node, "block")

                if body is not None:
                    for child in body.named_children:
                        visit(
                            child,
                            qualified_name,
                            kind == "class",
                        )

                return

        for child in node.named_children:
            visit(
                child,
                parent_qualified_name,
                inside_class,
            )

    visit(root)
    return symbols


def resolve_symbol(
    symbols: list[CodeSymbol],
    qualified_name: str,
) -> CodeSymbol | None:
    """Resolve an exact qualified symbol name.

    No fuzzy matching is performed. Ambiguous short names therefore
    cannot silently resolve to the wrong definition.
    """

    matches = [
        symbol
        for symbol in symbols
        if symbol.qualified_name == qualified_name
    ]

    if len(matches) != 1:
        return None

    return matches[0]