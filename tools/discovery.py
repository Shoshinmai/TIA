from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from langchain_core.tools import tool

from models import (
    ListDirectoryInput,
    SearchContentInput,
)
from utils.filesystem_helpers import safe_walk
from utils.location_resolver import resolve_location
from utils.text_helpers import (
    find_search_backend,
    is_binary_file,
)


MAX_RESULTS = 100
MAX_DIRECTORY_RESULTS = 500


def _search_files_sync(
    query: str,
    location: str = "current directory",
    recursive: bool = True,
    case_sensitive: bool = False,
) -> dict:
    """
    Synchronous implementation of search_files.
    """

    try:
        root_path = resolve_location(location)

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

    try:
        iterator = (
            root_path.rglob("*")
            if recursive
            else root_path.glob("*")
        )

        search_query = (
            query
            if case_sensitive
            else query.lower()
        )

        for path in iterator:

            if not path.is_file():
                continue

            filename = (
                path.name
                if case_sensitive
                else path.name.lower()
            )

            if search_query in filename:
                matches.append(
                    str(path.resolve())
                )

                if len(matches) >= MAX_RESULTS:
                    break

        return {
            "success": True,
            "query": query,
            "root": str(root_path.resolve()),
            "count": len(matches),
            "matches": matches,
            "truncated": len(matches) >= MAX_RESULTS,
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
) -> dict:
    """
    Locate files asynchronously when their exact location is unknown.
    """

    return await asyncio.to_thread(
        _search_files_sync,
        query,
        location,
        recursive,
        case_sensitive,
    )


def _list_directory_sync(
    location: str = "current directory",
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: int = 2,
) -> dict:
    """
    Synchronous implementation of list_directory.
    """

    try:
        root_path = resolve_location(location)

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

    for entry in safe_walk(
        root=root_path,
        recursive=recursive,
        include_hidden=include_hidden,
        max_depth=max_depth,
    ):
        relative = entry.relative_to(root_path)

        if entry.is_dir():
            directories.append(
                str(relative)
            )
            total_directories += 1

        else:
            files.append(
                str(relative)
            )
            total_files += 1

    truncated = False

    if len(directories) > MAX_DIRECTORY_RESULTS:
        directories = directories[
            :MAX_DIRECTORY_RESULTS
        ]
        truncated = True

    remaining = (
        MAX_DIRECTORY_RESULTS
        - len(directories)
    )

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


@tool(args_schema=ListDirectoryInput)
async def list_directory(
    location: str = "current directory",
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: int = 2,
) -> dict:
    """
    Inspect a directory asynchronously.
    """

    return await asyncio.to_thread(
        _list_directory_sync,
        location,
        recursive,
        include_hidden,
        max_depth,
    )


def _search_content_sync(
    query: str,
    location: str = "current directory",
    file_pattern: str = "*",
    case_sensitive: bool = False,
    max_results: int = 50,
) -> dict:
    """
    Synchronous implementation of search_content.

    Both the Python filesystem backend and the ripgrep backend
    remain unchanged. The entire operation is moved out of the
    event loop by the async wrapper.
    """

    try:
        root_path = resolve_location(location)

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
    )


@tool(args_schema=SearchContentInput)
async def search_content(
    query: str,
    location: str = "current directory",
    file_pattern: str = "*",
    case_sensitive: bool = False,
    max_results: int = 50,
) -> dict:
    """
    Search file contents asynchronously.
    """

    return await asyncio.to_thread(
        _search_content_sync,
        query,
        location,
        file_pattern,
        case_sensitive,
        max_results,
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
            "error": (
                "Ripgrep is not installed or "
                "is not available on PATH."
            ),
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
        }

    except Exception as exc:
        return {
            "success": False,
            "query": query,
            "backend": "ripgrep",
            "error": str(exc),
        }

    if (
        result.returncode not in (0, 1)
        or result.stderr.strip()
    ):
        return {
            "success": False,
            "query": query,
            "backend": "ripgrep",
            "root": str(root),
            "error": (
                result.stderr.strip()
                or (
                    "Ripgrep failed with return code "
                    f"{result.returncode}."
                )
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

    return {
        "success": True,
        "query": query,
        "backend": "ripgrep",
        "root": str(root),
        "count": len(matches),
        "matches": matches,
        "truncated": truncated,
    }


def _search_with_python(
    query: str,
    root: Path,
    file_pattern: str,
    case_sensitive: bool,
    max_results: int,
) -> dict:

    matches = []
    truncated = False

    search_query = (
        query
        if case_sensitive
        else query.lower()
    )

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

                    for line_number, line in enumerate(
                        file,
                        start=1,
                    ):
                        searchable_line = (
                            line
                            if case_sensitive
                            else line.lower()
                        )

                        if (
                            search_query
                            not in searchable_line
                        ):
                            continue

                        if (
                            len(matches)
                            >= max_results
                        ):
                            truncated = True
                            break

                        column = (
                            searchable_line.find(
                                search_query
                            )
                            + 1
                        )

                        matches.append(
                            {
                                "file": str(path),
                                "line": line_number,
                                "column": column,
                                "snippet": line.rstrip(
                                    "\r\n"
                                ),
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

    return {
        "success": True,
        "query": query,
        "backend": "python",
        "root": str(root),
        "count": len(matches),
        "matches": matches,
        "truncated": truncated,
    }