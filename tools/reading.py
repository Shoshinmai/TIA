from langchain_core.tools import tool
from datetime import datetime
from agents.terminal.models import GetFileInfoInput, ReadFileInput
from agents.terminal.utils.location_resolver import resolve_location
from agents.terminal.utils.text_helpers import read_lines


@tool(args_schema=ReadFileInput)
def read_file(
    path: str,
    start_line: int = 1,
) -> dict:
    """
    PURPOSE
    -------
    Read a bounded window of lines from a text file.

    The capability controls the maximum amount of content returned.
    The model controls only the file path and starting line.

    TYPICAL USE CASES
    -----------------
    - Inspect source code.
    - Read configuration files.
    - Examine logs around a relevant location.
    - Continue reading a large file using pagination.
    - Inspect a file found by search_files.
    - Read context around a match found by search_content.

    USE THIS CAPABILITY WHEN
    ------------------------
    - The file path is known.
    - File contents need to be inspected.
    - A bounded section of a file needs to be read.

    DO NOT USE THIS CAPABILITY WHEN
    -------------------------------
    - Searching for a file by name.
      Use search_files.

    - Searching for text across files.
      Use search_content.

    - Exploring a directory structure.
      Use list_directory.

    - Executing commands.
      Use run_terminal only when no specialized capability applies.

    IMPORTANT
    ---------
    The amount of content returned is controlled internally by
    the capability.

    The model MUST NOT choose a maximum number of lines.

    For large files, the result contains:

        has_more
        next_start_line
        total_lines
        remaining_lines

    To continue reading, call read_file again with the
    returned next_start_line.

    Returns
    -------
    Structured file content with pagination metadata.
    """

    try:
        resolved_path = resolve_location(path)

    except ValueError as exc:
        return {
            "success": False,
            "path": path,
            "error": str(exc),
        }

    if not resolved_path.is_file():
        return {
            "success": False,
            "path": str(resolved_path),
            "error": "Path is not a file.",
        }

    result = read_lines(
        path=resolved_path,
        start_line=start_line,
    )

    if result is None:
        return {
            "success": False,
            "path": str(resolved_path),
            "error": "Unable to read file.",
        }

    return {
        "success": True,
        "path": str(resolved_path),
        **result,
    }


@tool(args_schema=GetFileInfoInput)
def get_file_info(path: str) -> dict:
    """
    PURPOSE
    -------
    Retrieve lightweight filesystem metadata about a file or directory.

    This capability allows the Terminal Agent to inspect basic properties
    of a known filesystem path without reading file contents or traversing
    directory contents.

    TYPICAL USE CASES
    -----------------
    - Check the size of a file before deciding how to inspect it.
    - Determine whether a known path is a file or directory.
    - Inspect the extension and timestamps of a filesystem item.
    - Inspect metadata for a path discovered by search_files.

    USE THIS CAPABILITY WHEN
    ------------------------
    - The path is already known.
    - Filesystem metadata is needed.
    - The agent needs to inspect file size before choosing a reading or
      searching strategy.

    DO NOT USE THIS CAPABILITY WHEN
    -------------------------------
    - Searching for a file or directory by name.
      Use search_files.

    - Exploring directory contents.
      Use list_directory.

    - Searching for text inside files.
      Use search_content.

    - Reading file contents.
      Use read_file.

    IMPORTANT
    ---------
    This capability retrieves metadata only.

    It does not read file contents.

    It does not recursively inspect directories.

    Returns
    -------
    Structured filesystem metadata.
    """

    try:
        resolved_path = resolve_location(path)

    except ValueError as exc:
        return {
            "success": False,
            "path": path,
            "error": str(exc),
        }

    try:
        stat = resolved_path.stat()

    except (PermissionError, OSError) as exc:
        return {
            "success": False,
            "path": str(resolved_path),
            "error": str(exc),
        }
    if resolved_path.is_file():
        item_type = "file"

    elif resolved_path.is_dir():
        item_type = "directory"

    else:
        item_type = "other"

    extension = resolved_path.suffix if resolved_path.is_file() else None

    created_at = datetime.fromtimestamp(stat.st_ctime).isoformat()

    modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

    return {
        "success": True,
        "path": str(resolved_path),
        "name": resolved_path.name,
        "type": item_type,
        "extension": extension,
        "size_bytes": stat.st_size,
        "created_at": created_at,
        "modified_at": modified_at,
    }
