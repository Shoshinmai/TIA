from code_intelligence.parser import parse_source
from code_intelligence.symbols import (
    AmbiguousSymbolError,
    resolve_symbol,
)


def parse(source: str):
    return parse_source(source, ".py")


def test_extracts_top_level_function_and_class():
    result = parse(
        """
def standalone():
    pass


class Agent:
    pass
"""
    )

    symbols = {
        symbol.qualified_name: symbol
        for symbol in result.symbols
    }

    assert "standalone" in symbols
    assert "Agent" in symbols
    assert symbols["standalone"].kind == "function"
    assert symbols["Agent"].kind == "class"


def test_decorated_definition_is_extracted_once():
    result = parse(
        """
@staticmethod
def execute():
    pass
"""
    )

    matches = [
        symbol
        for symbol in result.symbols
        if symbol.qualified_name == "execute"
    ]

    assert len(matches) == 1
    assert matches[0].decorators == ["@staticmethod"]
    assert matches[0].source_range.start_line == 2


def test_decorated_class_is_extracted_once():
    result = parse(
        """
@dataclass
class Agent:
    pass
"""
    )

    matches = [
        symbol
        for symbol in result.symbols
        if symbol.qualified_name == "Agent"
    ]

    assert len(matches) == 1
    assert matches[0].decorators == ["@dataclass"]


def test_async_function_is_detected():
    result = parse(
        """
async def execute():
    pass
"""
    )

    symbol = result.symbols[0]

    assert symbol.qualified_name == "execute"
    assert symbol.is_async is True


def test_nested_function_inside_method_is_not_classified_as_method():
    result = parse(
        """
class Agent:
    def execute(self):
        def helper():
            pass

        return helper()
"""
    )

    symbols = {
        symbol.qualified_name: symbol
        for symbol in result.symbols
    }

    assert symbols["Agent.execute"].kind == "method"
    assert symbols["Agent.execute.helper"].kind == "function"


def test_nested_class_and_method_qualified_names():
    result = parse(
        """
class Outer:
    class Inner:
        def execute(self):
            pass
"""
    )

    qualified_names = {
        symbol.qualified_name
        for symbol in result.symbols
    }

    assert "Outer" in qualified_names
    assert "Outer.Inner" in qualified_names
    assert "Outer.Inner.execute" in qualified_names


def test_extracts_docstring_value():
    result = parse(
        '''
def execute():
    """Run the agent."""
    pass
'''
    )

    assert result.symbols[0].docstring == "Run the agent."


def test_extracts_import_statements():
    result = parse(
        """
import os
import pathlib
from collections import Counter
"""
    )

    assert [item.kind for item in result.imports] == [
        "import",
        "import",
        "from_import",
    ]

    assert [item.statement for item in result.imports] == [
        "import os",
        "import pathlib",
        "from collections import Counter",
    ]


def test_imports_have_source_ranges():
    result = parse(
        """
import os
from pathlib import Path
"""
    )

    assert result.imports[0].source_range.start_line == 2
    assert result.imports[1].source_range.start_line == 3


def test_malformed_python_returns_diagnostics():
    result = parse(
        """
def broken(
    pass
"""
    )

    assert result.success is False
    assert result.diagnostics


def test_resolve_symbol_returns_exact_match():
    result = parse(
        """
class Agent:
    def execute(self):
        pass
"""
    )

    symbol = resolve_symbol(
        result.symbols,
        "Agent.execute",
    )

    assert symbol is not None
    assert symbol.name == "execute"


def test_resolve_symbol_returns_none_when_missing():
    result = parse("def execute(): pass")

    assert resolve_symbol(result.symbols, "Agent.execute") is None


def test_resolve_symbol_raises_for_duplicate_qualified_names():
    result = parse(
        """
def execute():
    pass

def execute():
    return True
"""
    )

    try:
        resolve_symbol(result.symbols, "execute")
    except AmbiguousSymbolError:
        pass
    else:
        raise AssertionError("Expected AmbiguousSymbolError.")