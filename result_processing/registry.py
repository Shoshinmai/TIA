from collections.abc import Callable
from agents.terminal.result_processing.models import NormalizedResult
from agents.terminal.result_processing.normalizers.execution import (
    normalize_run_terminal,
)
from agents.terminal.result_processing.normalizers.filesystem import (
    normalize_list_directory,
    normalize_search_files,
    normalize_search_content,
    normalize_read_file,
    normalize_get_file_info,
)

from agents.terminal.result_processing.normalizers.artifact import (
    normalize_search_artifact,
    normalize_read_artifact,
)

NORMALIZER_REGISTRY: dict[
    str,
    Callable[..., NormalizedResult],
] = {
    "list_directory": normalize_list_directory,
    "search_files": normalize_search_files,
    "search_content": normalize_search_content,
    "read_file": normalize_read_file,
    "get_file_info": normalize_get_file_info,
    "search_artifact": normalize_search_artifact,
    "read_artifact": normalize_read_artifact,
    "run_terminal": normalize_run_terminal,
}
