from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path

from langchain_core.tools import tool

from models import (
    ListDirectoryInput,
    SearchContentInput,
)
from utils.filesystem_helpers import safe_walk
from utils.location_resolver import (
    get_workspace_root,
    resolve_location,
)
from utils.text_helpers import (
    find_search_backend,
    is_binary_file,
)


MAX_RESULTS = 100
MAX_DIRECTORY_RESULTS = 500
DEFAULT_MAX_DEPTH = 10
DEFAULT_TRAVERSAL_TIMEOUT = 30.0  # seconds


def _is_drive_root_search(
    location: str,
    workspace_root: Path | None = None,
) -> bool:
    """Check if the location resolves to a drive root."""
    try:
        root_path = resolve_location(
            location,
            workspace_root=workspace_root,
        )
        return len(root_path.parts) == 1 and root_path.drive == str(root_path)
    except Exception:
        return False


def _search_files_sync(
    query: str,
    location: str = "current directory",
    recursive: bool = True,
    case_sensitive: bool = False,
    max_depth: int = DEFAULT_MAX_DEPTH,
    allow_drive_root: bool = False,
    workspace_root: Path | None = None,
) -> dict:
    """
    Synchronous implementation of search_files with safety bounds.
    """

    # Gate drive-root searches
    if _is_drive_root_search(location, workspace_root) and not allow_drive_root:
        return {
            "success": False,
            "query": query,
            "location": location,
            "count": 0,
            "matches": [],
            "truncated": False,
            "error": "Drive-root search not allowed. Use a specific subdirectory.",
            "limit_reached": "drive_root_gate",
        }

    try:
        root_path = resolve_location(
            location,
            allow_drive_root=allow_drive_root,
            workspace_root=workspace_root,
        )

    except ValueError as exc:
        return {
            "success": False,
            "query": query,
            "location": location,
            "count": 0,
            "matches": [],
            "truncated": False,
            "error": str(exc),
        }

    matches = []
    traversal_start = time.time()
    timeout_reached = False

    try:
        iterator = safe_walk(
            root=root_path,
            recursive=recursive,
            include_hidden=False,
            max_depth=max_depth if recursive else 1,
            exclude_patterns=None,  # Uses DEFAULT_EXCLUDE_DIRS
        )

        search_query = query if case_sensitive else query.lower()

        for path in iterator:
            # Check traversal timeout
            if time.time() - traversal_start > DEFAULT_TRAVERSAL_TIMEOUT:
                timeout_reached = True
                break

            if not path.is_file():
                continue

            filename = path.name if case_sensitive else path.name.lower()

            if search_query in filename:
                matches.append(str(path.resolve()))

                if len(matches) >= MAX_RESULTS:
                    break

        truncated = len(matches) >= MAX_RESULTS or timeout_reached
        limit_reached = None
        if len(matches) >= MAX_RESULTS:
            limit_reached = "max_results"
        elif timeout_reached:
            limit_reached = "traversal_timeout"

        return {
            "success": True,
            "query": query,
            "root": str(root_path.resolve()),
            "count": len(matches),
            "matches": matches,
            "truncated": truncated,
            "limit_reached": limit_reached,
        }

    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "query": query,
        }


@tool
async def search_files(
    query: str,
    location: str = "current directory",
    recursive: bool = True,
    case_sensitive: bool = False,
    max_depth: int = DEFAULT_MAX_DEPTH,
    allow_drive_root: bool = False,
) -> dict:
    """
    Locate files asynchronously when their exact location is unknown.

    Safety bounds:
    - max_depth: Maximum recursion depth (default 10)
    - Traversal timeout: 30 seconds
    - Default exclusions: .git, node_modules, __pycache__, venv, etc.
    - Drive-root searches require explicit allow_drive_root=True
    - Results truncated at 100 matches
    """

    return await asyncio.to_thread(
        _search_files_sync,
        query,
        location,
        recursive,
        case_sensitive,
        max_depth,
        allow_drive_root,
        get_workspace_root(),
    )


def _list_directory_sync(
    location: str = "current directory",
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: int = 2,
    allow_drive_root: bool = False,
    workspace_root: Path | None = None,
) -> dict:
    """
    Synchronous implementation of list_directory with safety bounds.
    """

    # Gate drive-root searches
    if _is_drive_root_search(location, workspace_root) and not allow_drive_root:
        return {
            "success": False,
            "location": location,
            "error": "Drive-root search not allowed. Use a specific subdirectory.",
            "limit_reached": "drive_root_gate",
        }

    try:
        root_path = resolve_location(
            location,
            allow_drive_root=allow_drive_root,
            workspace_root=workspace_root,
        )

    except ValueError as exc:
        return {
            "success": False,
            "location": location,
            "error": str(exc),
        }

    directories = []
    files = []

    total_directories = 0
    total_files = 0
    traversal_start = time.time()
    timeout_reached = False

    for entry in safe_walk(
        root=root_path,
        recursive=recursive,
        include_hidden=include_hidden,
        max_depth=max_depth,
    ):
        # Check traversal timeout
        if time.time() - traversal_start > DEFAULT_TRAVERSAL_TIMEOUT:
            timeout_reached = True
            break

        relative = entry.relative_to(root_path)

        if entry.is_dir():
            directories.append(str(relative))
            total_directories += 1

        else:
            files.append(str(relative))
            total_files += 1

    truncated = False
    limit_reached = None

    if len(directories) > MAX_DIRECTORY_RESULTS:
        directories = directories[:MAX_DIRECTORY_RESULTS]
        truncated = True
        limit_reached = "max_results"

    remaining = MAX_DIRECTORY_RESULTS - len(directories)

    if remaining < 0:
        remaining = 0

    if len(files) > remaining:
        files = files[:remaining]
        truncated = True
        if limit_reached is None:
            limit_reached = "max_results"

    if timeout_reached:
        truncated = True
        limit_reached = "traversal_timeout"

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
        "limit_reached": limit_reached,
    }


@tool(args_schema=ListDirectoryInput)
async def list_directory(
    location: str = "current directory",
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: int = 2,
    allow_drive_root: bool = False,
) -> dict:
    """
    Inspect a directory asynchronously.

    Safety bounds:
    - max_depth: Maximum recursion depth (default 2)
    - Traversal timeout: 30 seconds
    - Default exclusions: .git, node_modules, __pycache__, venv, etc.
    - Drive-root searches require explicit allow_drive_root=True
    - Results truncated at 500 entries
    """

    return await asyncio.to_thread(
        _list_directory_sync,
        location,
        recursive,
        include_hidden,
        max_depth,
        allow_drive_root,
        get_workspace_root(),
    )


def _search_content_sync(
    query: str,
    location: str = "current directory",
    file_pattern: str = "*",
    case_sensitive: bool = False,
    max_results: int = 50,
    max_depth: int = DEFAULT_MAX_DEPTH,
    allow_drive_root: bool = False,
    workspace_root: Path | None = None,
) -> dict:
    """
    Synchronous implementation of search_content with safety bounds.

    Both the Python filesystem backend and the ripgrep backend
    remain unchanged. The entire operation is moved out of the
    event loop by the async wrapper.
    """

    # Gate drive-root searches
    if _is_drive_root_search(location, workspace_root) and not allow_drive_root:
        return {
            "success": False,
            "query": query,
            "location": location,
            "error": "Drive-root search not allowed. Use a specific subdirectory.",
            "limit_reached": "drive_root_gate",
        }

    try:
        root_path = resolve_location(
            location,
            allow_drive_root=allow_drive_root,
            workspace_root=workspace_root,
        )

    except ValueError as exc:
        return {
            "success": False,
            "query": query,
            "location": location,
            "error": str(exc),
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

    return _search_with_python(
        query=query,
        root=root_path,
        file_pattern=file_pattern,
        case_sensitive=case_sensitive,
        max_results=max_results,
        max_depth=max_depth,
    )


@tool(args_schema=SearchContentInput)
async def search_content(
    query: str,
    location: str = "current directory",
    file_pattern: str = "*",
    case_sensitive: bool = False,
    max_results: int = 50,
    max_depth: int = DEFAULT_MAX_DEPTH,
    allow_drive_root: bool = False,
) -> dict:
    """
    Search file contents asynchronously.

    Safety bounds:
    - max_depth: Maximum recursion depth (default 10)
    - Traversal timeout: 30 seconds (for Python backend)
    - Default exclusions: .git, node_modules, __pycache__, venv, etc.
    - Drive-root searches require explicit allow_drive_root=True
    - Results truncated at max_results
    """

    return await asyncio.to_thread(
        _search_content_sync,
        query,
        location,
        file_pattern,
        case_sensitive,
        max_results,
        max_depth,
        allow_drive_root,
        get_workspace_root(),
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
            "error": ("Ripgrep is not installed or " "is not available on PATH."),
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

        print(
            "COMMAND:",
            command,
        )

        print(
            "RETURN CODE:",
            result.returncode,
        )

        print(
            "STDOUT:",
            repr(result.stdout[:2000]),
        )

        print(
            "STDERR:",
            repr(result.stderr),
        )

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "query": query,
            "backend": "ripgrep",
            "error": "Search timed out.",
            "limit_reached": "subprocess_timeout",
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
            "error": (
                result.stderr.strip()
                or ("Ripgrep failed with return code " f"{result.returncode}.")
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

        data = event.get(
            "data",
            {},
        )

        path_data = data.get(
            "path",
            {},
        )

        lines_data = data.get(
            "lines",
            {},
        )

        submatches = data.get(
            "submatches",
            [],
        )

        file_path = path_data.get("text")
        snippet = lines_data.get(
            "text",
            "",
        ).rstrip("\r\n")

        line_number = data.get(
            "line_number",
        )

        if not file_path:
            continue

        column = None

        if submatches:
            column = submatches[0].get(
                "start",
            )

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

    limit_reached = "max_results" if truncated else None

    return {
        "success": True,
        "query": query,
        "backend": "ripgrep",
        "root": str(root),
        "count": len(matches),
        "matches": matches,
        "truncated": truncated,
        "limit_reached": limit_reached,
    }


def _search_with_python(
    query: str,
    root: Path,
    file_pattern: str,
    case_sensitive: bool,
    max_results: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> dict:

    matches = []
    truncated = False
    timeout_reached = False
    traversal_start = time.time()

    search_query = query if case_sensitive else query.lower()

    try:
        for path in safe_walk(
            root=root,
            recursive=True,
            include_hidden=False,
            max_depth=max_depth,
        ):
            # Check traversal timeout
            if time.time() - traversal_start > DEFAULT_TRAVERSAL_TIMEOUT:
                timeout_reached = True
                break

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

                    for line_number, line in enumerate(
                        file,
                        start=1,
                    ):
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

            except (
                PermissionError,
                OSError,
                UnicodeError,
            ):
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

    limit_reached = None
    if truncated:
        limit_reached = "max_results"
    elif timeout_reached:
        limit_reached = "traversal_timeout"

    return {
        "success": True,
        "query": query,
        "backend": "python",
        "root": str(root),
        "count": len(matches),
        "matches": matches,
        "truncated": truncated or timeout_reached,
        "limit_reached": limit_reached,
    }
