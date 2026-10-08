from __future__ import annotations

import asyncio
from datetime import datetime

from langchain_core.tools import tool

from models import GetFileInfoInput, ReadFileInput
from utils.location_resolver import resolve_location
from utils.text_helpers import read_lines


def _read_file_sync(
    path: str,
    start_line: int = 1,
) -> dict:
    """
    Synchronous implementation of read_file.

    This function contains the existing filesystem behavior.
    It is executed through asyncio.to_thread() by the public
    async tool wrapper.
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


@tool(args_schema=ReadFileInput)
async def read_file(
    path: str,
    start_line: int = 1,
) -> dict:
    """
    Read a bounded window of lines from a text file asynchronously.

    The filesystem operation itself runs outside the event loop.
    """

    return await asyncio.to_thread(
        _read_file_sync,
        path,
        start_line,
    )


def _get_file_info_sync(
    path: str,
) -> dict:
    """
    Synchronous implementation of get_file_info.
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

    extension = (
        resolved_path.suffix
        if resolved_path.is_file()
        else None
    )

    created_at = datetime.fromtimestamp(
        stat.st_ctime
    ).isoformat()

    modified_at = datetime.fromtimestamp(
        stat.st_mtime
    ).isoformat()

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


@tool(args_schema=GetFileInfoInput)
async def get_file_info(
    path: str,
) -> dict:
    """
    Retrieve filesystem metadata asynchronously.
    """

    return await asyncio.to_thread(
        _get_file_info_sync,
        path,
    )