import pytest

from code_intelligence.models import CodeParseResult
from code_intelligence.parser import (
    LANGUAGE_ADAPTERS,
    LanguageAdapter,
    get_language_adapter,
    parse_source,
    register_language_adapter,
)


def test_python_adapter_is_registered():
    adapter = get_language_adapter(".py")

    assert adapter is not None
    assert adapter.language == "python"


def test_extension_lookup_is_case_insensitive():
    assert get_language_adapter(".PY") is get_language_adapter(".py")


def test_parse_source_uses_registered_adapter():
    result = parse_source(
        "def execute(): pass",
        ".py",
    )

    assert isinstance(result, CodeParseResult)
    assert result.language == "python"
    assert result.success is True


def test_parse_source_rejects_unsupported_extension():
    with pytest.raises(ValueError, match="unsupported_language"):
        parse_source("some source", ".unknown")


def test_adapter_registration_rejects_extension_without_dot():
    adapter = LanguageAdapter(
        language="example",
        extensions=("example",),
        parse=lambda source: CodeParseResult(
            language="example",
            success=True,
            total_lines=0,
        ),
    )

    with pytest.raises(ValueError, match="start with"):
        register_language_adapter(adapter)


def test_adapter_registration_rejects_duplicate_extension():
    adapter = LanguageAdapter(
        language="duplicate",
        extensions=(".py",),
        parse=lambda source: CodeParseResult(
            language="duplicate",
            success=True,
            total_lines=0,
        ),
    )

    with pytest.raises(ValueError, match="already registered"):
        register_language_adapter(adapter)


def test_adapter_registration_is_atomic_on_duplicate():
    new_extension = ".atomic-test"

    adapter = LanguageAdapter(
        language="example",
        extensions=(new_extension, ".py"),
        parse=lambda source: CodeParseResult(
            language="example",
            success=True,
            total_lines=0,
        ),
    )

    assert new_extension not in LANGUAGE_ADAPTERS

    with pytest.raises(ValueError, match="already registered"):
        register_language_adapter(adapter)

    # The first extension must not have been inserted before the
    # duplicate second extension caused registration to fail.
    assert new_extension not in LANGUAGE_ADAPTERS


def test_adapter_registration_rejects_duplicate_extensions_in_same_adapter():
    adapter = LanguageAdapter(
        language="example",
        extensions=(".example", ".EXAMPLE"),
        parse=lambda source: CodeParseResult(
            language="example",
            success=True,
            total_lines=0,
        ),
    )

    with pytest.raises(ValueError, match="duplicate extensions"):
        register_language_adapter(adapter)

    assert ".example" not in LANGUAGE_ADAPTERS


def test_adapter_registration_rejects_empty_extensions():
    adapter = LanguageAdapter(
        language="example",
        extensions=(),
        parse=lambda source: CodeParseResult(
            language="example",
            success=True,
            total_lines=0,
        ),
    )

    with pytest.raises(ValueError, match="at least one extension"):
        register_language_adapter(adapter)