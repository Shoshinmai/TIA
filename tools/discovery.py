from __future__ import annotations

import asyncio
import heapq
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from langchain_core.tools import tool
from rapidfuzz import fuzz

from models import (
    ListDirectoryInput,
    ListDirectoryResult,
    SearchContentInput,
    SearchFilesInput,
    SearchFilesResult,
)
from utils.filesystem_helpers import is_excluded, is_hidden, safe_walk
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


MATCH_PRIORITY = {
    "exact": 5,
    "prefix": 4,
    "substring": 3,
    "token": 2,
    "fuzzy": 1,
}

FUZZY_MATCH_THRESHOLD = 75.0
MAX_TRAVERSAL_ERRORS = 20


def _normalize_search_text(value: str, case_sensitive: bool) -> str:
    return value if case_sensitive else value.casefold()


def _match_text(
    query: str,
    candidate: str,
) -> tuple[str, float] | None:
    """
    Return the strongest match class and its score for one candidate.
    """

    if not candidate:
        return None

    if candidate == query:
        return "exact", 100.0

    if candidate.startswith(query):
        return "prefix", 95.0

    if query in candidate:
        return "substring", 90.0

    query_tokens = set(re.findall(r"\w+", query))
    candidate_tokens = set(re.findall(r"\w+", candidate))

    if query_tokens and query_tokens.issubset(candidate_tokens):
        return "token", 85.0

    # Avoid unreliable fuzzy matches for very short queries.
    if len(query) < 3:
        return None

    fuzzy_score = float(fuzz.ratio(query, candidate))

    if fuzzy_score >= FUZZY_MATCH_THRESHOLD:
        return "fuzzy", fuzzy_score

    return None


def _match_file(
    query: str,
    filename: str,
    relative_path: str,
    case_sensitive: bool,
) -> dict | None:
    """
    Match against both filename and relative path.

    The strongest match class wins. If both fields produce the same
    class and score, the filename match wins.
    """

    normalized_query = _normalize_search_text(query, case_sensitive)

    normalized_filename = _normalize_search_text(
        filename,
        case_sensitive,
    )

    normalized_relative_path = _normalize_search_text(
        relative_path,
        case_sensitive,
    )

    candidates = []

    filename_match = _match_text(
        normalized_query,
        normalized_filename,
    )

    if filename_match is not None:
        candidates.append(
            {
                "match_type": filename_match[0],
                "score": filename_match[1],
                "matched_on": "filename",
            }
        )

    path_match = _match_text(
        normalized_query,
        normalized_relative_path,
    )

    if path_match is not None:
        candidates.append(
            {
                "match_type": path_match[0],
                "score": path_match[1],
                "matched_on": "relative_path",
            }
        )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: (
            MATCH_PRIORITY[item["match_type"]],
            item["score"],
            item["matched_on"] == "filename",
        ),
    )


def _search_files_sync(
    query: str,
    location: str = "current directory",
    recursive: bool = True,
    case_sensitive: bool = False,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_results: int = MAX_RESULTS,
    workspace_root: Path | None = None,
) -> dict:
    """
    Bounded filename and filesystem-path discovery.

    Traverses the eligible search space and retains the best
    max_results matches rather than the first matches encountered.
    """

    query = query.strip()

    if not query:
        return SearchFilesResult(
            success=False,
            query=query,
            error="Search query cannot be empty.",
            complete=False,
        ).model_dump()

    if _is_drive_root_search(location, workspace_root):
        return SearchFilesResult(
            success=False,
            query=query,
            error="Drive-root search not allowed. Use a specific subdirectory.",
            complete=False,
            limit_reached="drive_root_gate",
        ).model_dump()

    try:
        root_path = resolve_location(
            location,
            workspace_root=workspace_root,
            allow_drive_root=False,
        )

        if not root_path.is_dir():
            raise ValueError(f"Search location is not a directory: {location}")

        resolved_root = root_path.resolve()

    except (ValueError, OSError) as exc:
        return SearchFilesResult(
            success=False,
            query=query,
            error=str(exc),
            complete=False,
        ).model_dump()

    traversal_start = time.monotonic()

    total_matches = 0
    skipped_symlinks = 0
    traversal_errors = []
    depth_limit_reached = False
    timeout_reached = False

    # The heap retains only the best max_results candidates.
    top_matches = []

    def record_error(path: Path, exc: OSError) -> None:
        if len(traversal_errors) < MAX_TRAVERSAL_ERRORS:
            traversal_errors.append(f"{path}: {exc.__class__.__name__}: {exc}")

    def record_symlink(path: Path) -> None:
        nonlocal skipped_symlinks
        skipped_symlinks += 1

    def record_depth_limit(path: Path) -> None:
        nonlocal depth_limit_reached
        depth_limit_reached = True

    try:
        iterator = safe_walk(
            root=root_path,
            recursive=recursive,
            include_hidden=False,
            max_depth=max_depth if recursive else 1,
            exclude_patterns=None,
            skip_symlinks=True,
            on_error=record_error,
            on_symlink=record_symlink,
            on_depth_limit=record_depth_limit,
        )

        for path in iterator:
            if time.monotonic() - traversal_start > DEFAULT_TRAVERSAL_TIMEOUT:
                timeout_reached = True
                break

            try:
                if not path.is_file():
                    continue

                relative_path = path.relative_to(root_path).as_posix()

                match = _match_file(
                    query=query,
                    filename=path.name,
                    relative_path=relative_path,
                    case_sensitive=case_sensitive,
                )

                if match is None:
                    continue

                total_matches += 1

                absolute_path = str(path.resolve())

                match_data = {
                    "path": absolute_path,
                    "relative_path": relative_path,
                    "match_type": match["match_type"],
                    "matched_on": match["matched_on"],
                    "score": match["score"],
                }

                # Higher priority, score, and filename preference rank first.
                # The normalized path provides deterministic tie-breaking.
                rank = (
                    MATCH_PRIORITY[match["match_type"]],
                    match["score"],
                    int(match["matched_on"] == "filename"),
                    relative_path.casefold(),
                    relative_path,
                )

                heap_item = (rank, match_data)

                if len(top_matches) < max_results:
                    heapq.heappush(top_matches, heap_item)

                elif rank > top_matches[0][0]:
                    heapq.heapreplace(top_matches, heap_item)

            except OSError as exc:
                record_error(path, exc)

    except Exception as exc:
        return SearchFilesResult(
            success=False,
            query=query,
            root=str(resolved_root),
            complete=False,
            traversal_errors=traversal_errors,
            skipped_symlinks=skipped_symlinks,
            error=str(exc),
        ).model_dump()

    ranked_matches = [
        item[1]
        for item in sorted(
            top_matches,
            key=lambda item: item[0],
            reverse=True,
        )
    ]

    complete = not (timeout_reached or depth_limit_reached or traversal_errors)

    limit_reached = None

    if timeout_reached:
        limit_reached = "traversal_timeout"
    elif depth_limit_reached:
        limit_reached = "max_depth"
    elif traversal_errors:
        limit_reached = "traversal_error"
    elif total_matches > len(ranked_matches):
        limit_reached = "max_results"

    truncated = total_matches > len(ranked_matches) or not complete

    return SearchFilesResult(
        success=True,
        query=query,
        root=str(resolved_root),
        matches=ranked_matches,
        returned_count=len(ranked_matches),
        total_matches=total_matches,
        complete=complete,
        truncated=truncated,
        limit_reached=limit_reached,
        traversal_errors=traversal_errors,
        skipped_symlinks=skipped_symlinks,
    ).model_dump()


@tool(args_schema=SearchFilesInput)
async def search_files(
    query: str,
    location: str = "current directory",
    recursive: bool = True,
    case_sensitive: bool = False,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_results: int = MAX_RESULTS,
) -> dict:
    """
    Discover files by filename and relative filesystem path.

    Supports exact, prefix, substring, token-based, and fuzzy matching.

    Safety bounds:
    - Maximum traversal depth: 10 by default
    - Maximum traversal time: 30 seconds
    - Maximum returned matches: 100
    - Symlinks are never followed
    - Drive-root searches are not allowed
    """

    return await asyncio.to_thread(
        _search_files_sync,
        query,
        location,
        recursive,
        case_sensitive,
        max_depth,
        max_results,
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
    Bounded directory listing using os.scandir().

    Results are ordered deterministically within each directory.
    At most MAX_DIRECTORY_RESULTS entries are returned across
    files and directories combined.
    """

    def make_result(**kwargs) -> dict:
        return ListDirectoryResult(**kwargs).model_dump()

    if _is_drive_root_search(location, workspace_root) and not allow_drive_root:
        return make_result(
            success=False,
            location=location,
            recursive=recursive,
            complete=False,
            limit_reached="drive_root_gate",
            error="Drive-root search not allowed. Use a specific subdirectory.",
        )

    try:
        root_path = resolve_location(
            location,
            allow_drive_root=allow_drive_root,
            workspace_root=workspace_root,
        )

        if not root_path.is_dir():
            raise ValueError(f"Location is not a directory: {location}")

        resolved_root = root_path.resolve()

    except (ValueError, OSError) as exc:
        return make_result(
            success=False,
            location=location,
            recursive=recursive,
            complete=False,
            error=str(exc),
        )

    traversal_start = time.monotonic()

    directories = []
    files = []

    total_directories = 0
    total_files = 0

    skipped_symlinks = 0
    traversal_errors = []

    timeout_reached = False
    depth_limit_reached = False
    max_results_reached = False

    def record_error(path: Path, exc: OSError) -> None:
        if len(traversal_errors) < MAX_TRAVERSAL_ERRORS:
            traversal_errors.append(f"{path}: {exc.__class__.__name__}: {exc}")

    def timed_out() -> bool:
        return time.monotonic() - traversal_start >= DEFAULT_TRAVERSAL_TIMEOUT

    def collect_entries(directory: Path):
        """
        Collect at most MAX_DIRECTORY_RESULTS + 1 eligible entries.

        heapq.nsmallest() keeps memory bounded while selecting the
        lexicographically smallest entries. The extra entry allows
        the caller to detect that more entries exist than the cap.
        """
        nonlocal skipped_symlinks
        nonlocal timeout_reached

        candidates = []

        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    if timed_out():
                        timeout_reached = True
                        break

                    entry_path = Path(entry.path)

                    try:
                        if entry.is_symlink():
                            skipped_symlinks += 1
                            continue

                        if not include_hidden and is_hidden(entry_path):
                            continue

                        if is_excluded(entry_path):
                            continue

                        is_directory = entry.is_dir(follow_symlinks=False)

                        sort_key = (
                            entry.name.casefold(),
                            entry.name,
                        )

                        candidates.append((sort_key, entry.name, is_directory))

                        if len(candidates) > MAX_DIRECTORY_RESULTS:
                            candidates = heapq.nsmallest(
                                MAX_DIRECTORY_RESULTS + 1,
                                candidates,
                                key=lambda item: item[0],
                            )

                    except OSError as exc:
                        record_error(entry_path, exc)

        except OSError as exc:
            record_error(directory, exc)

        candidates.sort(key=lambda item: item[0])
        return candidates

    def has_eligible_children(directory: Path) -> bool:
        """
        Check whether a depth-boundary directory contains at least
        one eligible child without following symbolic links.
        """
        nonlocal skipped_symlinks
        nonlocal timeout_reached

        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    if timed_out():
                        timeout_reached = True
                        return False

                    entry_path = Path(entry.path)

                    try:
                        if entry.is_symlink():
                            skipped_symlinks += 1
                            continue

                        if not include_hidden and is_hidden(entry_path):
                            continue

                        if is_excluded(entry_path):
                            continue

                        return True

                    except OSError as exc:
                        record_error(entry_path, exc)

        except OSError as exc:
            record_error(directory, exc)

        return False

    # Each stack frame contains a directory's bounded, sorted entries.
    # The frame is resumed after a child directory has been traversed,
    # preserving depth-first traversal.
    stack = [(root_path, 1, iter(collect_entries(root_path)))]

    while stack:
        if timed_out():
            timeout_reached = True
            break

        current_directory, current_depth, entries = stack[-1]

        try:
            _, name, is_directory = next(entries)

        except StopIteration:
            stack.pop()
            continue

        entry_path = current_directory / name
        relative_path = entry_path.relative_to(root_path).as_posix()

        if is_directory:
            total_directories += 1

            if len(directories) + len(files) >= MAX_DIRECTORY_RESULTS:
                max_results_reached = True
                break

            directories.append(relative_path)

            if not recursive:
                continue

            if current_depth >= max_depth:
                if has_eligible_children(entry_path):
                    depth_limit_reached = True

                if timeout_reached:
                    break

                continue

            child_entries = collect_entries(entry_path)

            if timeout_reached:
                break

            stack.append(
                (
                    entry_path,
                    current_depth + 1,
                    iter(child_entries),
                )
            )

        else:
            total_files += 1

            if len(directories) + len(files) >= MAX_DIRECTORY_RESULTS:
                max_results_reached = True
                break

            files.append(relative_path)

    complete = not (
        timeout_reached
        or depth_limit_reached
        or traversal_errors
        or max_results_reached
    )

    limit_reached = None

    if timeout_reached:
        limit_reached = "traversal_timeout"
    elif max_results_reached:
        limit_reached = "max_results"
    elif depth_limit_reached:
        limit_reached = "max_depth"
    elif traversal_errors:
        limit_reached = "traversal_error"

    truncated = not complete

    return make_result(
        success=True,
        location=location,
        resolved_path=str(resolved_root),
        directories=directories,
        files=files,
        returned_directories=len(directories),
        returned_files=len(files),
        total_directories=total_directories,
        total_files=total_files,
        recursive=recursive,
        complete=complete,
        truncated=truncated,
        limit_reached=limit_reached,
        traversal_errors=traversal_errors,
        skipped_symlinks=skipped_symlinks,
    )


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
    - Maximum combined returned files and directories: 500
    - Results are ordered deterministically within each directory
    - Default exclusions: .git, node_modules, __pycache__, venv, etc.
    - Symbolic links are skipped and never followed
    - Drive-root searches require explicit allow_drive_root=True

    Returns a structured listing with completeness, truncation,
    traversal errors, and skipped symlink information.
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
