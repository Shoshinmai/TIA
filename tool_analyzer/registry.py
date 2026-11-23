from enum import StrEnum


class ToolAnalyzerFamily(StrEnum):
    DISCOVERY = "searcher"
    FILE_INSPECTION = "reader"
    TERMINAL = "terminal"
    ARTIFACT = "artifact"


# Every capability requiring specialized analysis must be
# explicitly registered here.
TOOL_ANALYZER_REGISTRY: dict[str, ToolAnalyzerFamily] = {
    # Discovery Analyzer
    "search_files": ToolAnalyzerFamily.DISCOVERY,
    "list_directory": ToolAnalyzerFamily.DISCOVERY,
    "search_content": ToolAnalyzerFamily.DISCOVERY,

    # File Inspection Analyzer
    "read_file": ToolAnalyzerFamily.FILE_INSPECTION,
    "get_file_info": ToolAnalyzerFamily.FILE_INSPECTION,

    # Terminal Analyzer
    "run_terminal": ToolAnalyzerFamily.TERMINAL,

    # Artifact Analyzer
    "search_artifact": ToolAnalyzerFamily.ARTIFACT,
    "read_artifact": ToolAnalyzerFamily.ARTIFACT,
}


def resolve_tool_analyzer_family(
    tool_name: str,
) -> ToolAnalyzerFamily | None:
    """Resolve a capability to its explicitly registered analyzer family.

    Unknown capability names return None. No inference or fallback routing
    is performed.
    """
    return TOOL_ANALYZER_REGISTRY.get(tool_name)