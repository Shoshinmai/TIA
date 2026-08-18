import json
import shutil
import string
from pathlib import Path
import subprocess
import shlex
from langchain_core.tools import tool

from agents.terminal.models import ListDirectoryInput, SearchContentInput
from agents.terminal.utils.location_resolver import resolve_location
from agents.terminal.utils.filesystem_helpers import safe_walk
from agents.terminal.utils.text_helpers import (
    find_search_backend,
    safe_read_text,
    is_binary_file,
)

# from .terminal.utils.location_resolver import resolve_location


MAX_RESULTS = 100
MAX_DIRECTORY_RESULTS = 500


@tool
def search_files(
    query: str,
    location: str = "current directory",
    recursive: bool = True,
    case_sensitive: bool = False,
) -> dict:
    """
    PURPOSE
    -------
    Locate files when their exact location is unknown.

    This capability searches for files by filename or filename pattern
    within a specified location.

    Use this capability before attempting to read or modify a file whose
    location is not yet known.

    TYPICAL USE CASES
    -----------------
    - Find a file by name.
    - Locate source code files.
    - Search for configuration files.
    - Locate logs or reports.

    USE THIS CAPABILITY WHEN
    ------------------------
    - The user knows the filename but not its location.
    - A file must be located before reading or editing.
    - Searching by filename is sufficient.

    DO NOT USE THIS CAPABILITY WHEN
    -------------------------------
    - Exploring an unknown directory structure.
      Use list_directory.

    - Searching inside file contents.
      Use search_content.

    - Reading a file.
      Use read_file.

    - Executing shell commands.
      Use run_terminal only if no specialized capability applies.

    IMPORTANT
    ---------
    Repeating this capability with only minor changes to the search
    query is usually not a new strategy.

    If previous searches have clearly failed, consider another
    capability instead.

    Returns
    -------
    Structured search results containing matched files and metadata.
    """
    # search_files.category = "Discovery"

    try:
        root_path = resolve_location(location)
    except ValueError as e:
        return {
            "success": False,
            "query": query,
            "location": location,
            "count": 0,
            "matches": [],
            "truncated": False,
            "error": str(e),
        }
    max_results = MAX_RESULTS

    matches = []

    try:
        iterator = root_path.rglob("*") if recursive else root_path.glob("*")

        for path in iterator:

            if not path.is_file():
                continue

            filename = path.name if case_sensitive else path.name.lower()
            search_query = query if case_sensitive else query.lower()

            if search_query in filename:
                matches.append(str(path.resolve()))

                if len(matches) >= max_results:
                    break

        return {
            "success": True,
            "query": query,
            "root": str(root_path.resolve()),
            "count": len(matches),
            "matches": matches,
            "truncated": len(matches) >= max_results,
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e),
            "query": query,
        }


@tool(args_schema=ListDirectoryInput)
def list_directory(
    location: str = "current directory",
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: int = 2,
) -> dict:
    """
    PURPOSE
    -------
    Inspect the structure and contents of a directory.

    This capability helps the planner understand how files
    and folders are organized before selecting files to read
    or modify.

    TYPICAL USE CASES
    -----------------
    - Explore a project.
    - Inspect an unfamiliar folder.
    - Locate configuration directories.
    - Understand repository layout.
    - Count files and folders.

    USE THIS CAPABILITY WHEN
    ------------------------
    - The directory structure is unknown.
    - The planner needs to discover where files are located.
    - Browsing folders is more appropriate than searching by filename.

    DO NOT USE THIS CAPABILITY WHEN
    -------------------------------
    - Searching for a known filename.
      Use search_files.

    - Reading file contents.
      Use read_file.

    - Searching inside files.
      Use search_content.

    - Executing shell commands.
      Use run_terminal only if no specialized capability applies.

    IMPORTANT
    ---------
    Directory exploration should normally precede reading
    or modifying files in unfamiliar locations.
    Maximum traversal depth is controlled by the max_depth argument.

    Returns
    -------
    Structured directory information including folders,
    files, summary counts, and traversal metadata.
    """

    #     list_directory.category = "Discovery"
    #     list_directory.return_description = """
    # Returns:

    # - success
    # - resolved_path
    # - directories
    # - files
    # - total_directories
    # - total_files
    # - recursive
    # - truncated
    # """
    #     list_directory.usage_notes = """
    # Use this capability to inspect a directory.

    # Do not use it to locate files by name.

    # Use search_files instead.

    # Do not use it to read files.

    # Use read_file instead.
    # """
    try:
        root_path = resolve_location(location)

    except ValueError as e:

        return {
            "success": False,
            "location": location,
            "error": str(e),
        }

    directories = []
    files = []

    total_directories = 0
    total_files = 0

    for entry in safe_walk(
        root=root_path,
        recursive=recursive,
        include_hidden=include_hidden,
        max_depth=max_depth,
    ):
        relative = entry.relative_to(root_path)

        if entry.is_dir():

            directories.append(str(relative))
            total_directories += 1

        else:

            files.append(str(relative))
            total_files += 1

    truncated = False

    if len(directories) > MAX_DIRECTORY_RESULTS:

        directories = directories[:MAX_DIRECTORY_RESULTS]
        truncated = True

    remaining = MAX_DIRECTORY_RESULTS - len(directories)

    if remaining < 0:
        remaining = 0

    if len(files) > remaining:

        files = files[:remaining]
        truncated = True

    return {
        "success": True,
        "location": location,
        "resolved_path": str(root_path),
        "directories": directories,
        "files": files,
        "total_directories": total_directories,
        "total_files": total_files,
        "recursive": recursive,
        "truncated": truncated,
    }


@tool(args_schema=SearchContentInput)
def search_content(
    query: str,
    location: str = "current directory",
    file_pattern: str = "*",
    case_sensitive: bool = False,
    max_results: int = 50,
) -> dict:
    """
    PURPOSE
    -------
    Locate files by searching inside their contents.

    This capability searches text contained within files rather
    than searching filenames.

    TYPICAL USE CASES
    -----------------
    - Find a function definition.
    - Locate configuration values.
    - Search for error messages.
    - Locate TODO comments.
    - Find class names.
    - Search log files.

    USE THIS CAPABILITY WHEN
    ------------------------
    - The filename is unknown.
    - The user knows text contained inside a file.
    - Searching by file contents is appropriate.

    DO NOT USE THIS CAPABILITY WHEN
    -------------------------------
    - Searching for filenames.
      Use search_files.

    - Browsing directory structures.
      Use list_directory.

    - Reading a file.
      Use read_file.

    - Executing shell commands.
      Use run_terminal only if no specialized capability applies.

    IMPORTANT
    ---------
    Search results should contain matching files, line numbers,
    and small snippets that help identify relevant results.
    It is mandatory to give file pattern.
    It is mandatory to give location.

    Returns
    -------
    Structured content search results and search metadata.
    """

    try:
        root_path = resolve_location(location)

    except ValueError as e:
        return {
            "success": False,
            "query": query,
            "location": location,
            "error": str(e),
        }

    backend = find_search_backend()

    if backend == "ripgrep":
        return _search_with_ripgrep(
            query=query,
            root=root_path,
            file_pattern=file_pattern,
            case_sensitive=case_sensitive,
            max_results=max_results,
        )

    # if backend == "grep":
    #     return _search_with_grep(
    #         query=query,
    #         root=root_path,
    #         file_pattern=file_pattern,
    #         case_sensitive=case_sensitive,
    #         max_results=max_results,
    #     )

    return _search_with_python(
        query=query,
        root=root_path,
        file_pattern=file_pattern,
        case_sensitive=case_sensitive,
        max_results=max_results,
    )


def _search_with_ripgrep(
    query: str,
    root: Path,
    file_pattern: str,
    case_sensitive: bool,
    max_results: int,
) -> dict:
    if shutil.which("rg") is None:
        return {
            "success": False,
            "query": query,
            "backend": "ripgrep",
            "root": str(root),
            "error": "Ripgrep is not installed or is not available on PATH.",
        }
    command = [
        "rg",
        "--json",
        "--glob",
        file_pattern,
    ]

    if not case_sensitive:
        command.append("-i")

    command.append(query)
    command.append(str(root))

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )
        print("COMMAND:", command)
        print("RETURN CODE:", result.returncode)
        print("STDOUT:", repr(result.stdout[:2000]))
        print("STDERR:", repr(result.stderr))

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "query": query,
            "backend": "ripgrep",
            "error": "Search timed out.",
        }

    except Exception as exc:
        return {
            "success": False,
            "query": query,
            "backend": "ripgrep",
            "error": str(exc),
        }

    if result.returncode not in (0, 1) or result.stderr.strip():
        return {
            "success": False,
            "query": query,
            "backend": "ripgrep",
            "root": str(root),
            "error": result.stderr.strip() or (
                f"Ripgrep failed with return code {result.returncode}."
            ),
        }

    matches = []
    truncated = False

    for output_line in result.stdout.splitlines():

        try:
            event = json.loads(output_line)
        except json.JSONDecodeError:
            continue

        if event.get("type") != "match":
            continue

        data = event.get("data", {})

        path_data = data.get("path", {})
        lines_data = data.get("lines", {})
        submatches = data.get("submatches", [])

        file_path = path_data.get("text")
        snippet = lines_data.get("text", "").rstrip("\r\n")
        line_number = data.get("line_number")

        if not file_path:
            continue

        column = None

        if submatches:
            column = submatches[0].get("start")

            if column is not None:
                column += 1

        if len(matches) >= max_results:
            truncated = True
            break

        matches.append(
            {
                "file": file_path,
                "line": line_number,
                "column": column,
                "snippet": snippet,
            }
        )
    return {
        "success": True,
        "query": query,
        "backend": "ripgrep",
        "root": str(root),
        "count": len(matches),
        "matches": matches,
        "truncated": truncated,
    }


def _search_with_grep(
    query: str,
    root: Path,
    file_pattern: str,
    case_sensitive: bool,
    max_results: int,
) -> dict:
    raise NotImplementedError


def _search_with_python(
    query: str,
    root: Path,
    file_pattern: str,
    case_sensitive: bool,
    max_results: int,
) -> dict:

    matches = []
    truncated = False

    search_query = query if case_sensitive else query.lower()

    try:
        for path in safe_walk(
            root=root,
            recursive=True,
            include_hidden=False,
            max_depth=None,
        ):
            if not path.is_file():
                continue

            if not path.match(file_pattern):
                continue

            if is_binary_file(path):
                continue

            try:
                with path.open(
                    "r",
                    encoding="utf-8",
                    errors="replace",
                ) as file:

                    for line_number, line in enumerate(file, start=1):

                        searchable_line = line if case_sensitive else line.lower()

                        if search_query not in searchable_line:
                            continue

                        if len(matches) >= max_results:
                            truncated = True
                            break

                        column = searchable_line.find(search_query) + 1

                        matches.append(
                            {
                                "file": str(path),
                                "line": line_number,
                                "column": column,
                                "snippet": line.rstrip("\r\n"),
                            }
                        )

            except (PermissionError, OSError, UnicodeError):
                continue

            if truncated:
                break

    except Exception as exc:
        return {
            "success": False,
            "query": query,
            "backend": "python",
            "root": str(root),
            "error": str(exc),
        }

    return {
        "success": True,
        "query": query,
        "backend": "python",
        "root": str(root),
        "count": len(matches),
        "matches": matches,
        "truncated": truncated,
    }


# print(search_files.invoke({"query": "main.py"}))
