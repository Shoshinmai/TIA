from __future__ import annotations

import asyncio
import codecs
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

from models import GetFileInfoInput, ReadFileInput
from utils.location_resolver import get_workspace_root, resolve_location
from utils.text_helpers import read_lines


def _decode_complete_text(raw: bytes) -> tuple[str, str]:
    """Decode complete file contents without silently replacing bytes."""

    encodings = (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    )

    for bom, encoding in encodings:
        if raw.startswith(bom):
            try:
                return raw.decode(encoding, errors="strict"), encoding
            except UnicodeDecodeError as exc:
                raise UnicodeDecodeError(
                    exc.encoding,
                    exc.object,
                    exc.start,
                    exc.end,
                    exc.reason,
                ) from exc

    # Reject likely binary content rather than interpreting it as text.
    if b"\x00" in raw[:8192]:
        raise ValueError("unsupported_binary")

    return raw.decode("utf-8", errors="strict"), "utf-8"


def _read_file_sync(
    path: str,
    workspace_root: Path | None = None,
) -> dict:
    """Read and return the complete contents of a text file."""

    try:
        resolved_path = resolve_location(path, workspace_root)

    except ValueError as exc:
        return {
            "success": False,
            "path": path,
            "error_code": "not_found",
            "error": str(exc),
        }

    try:
        if not resolved_path.is_file():
            return {
                "success": False,
                "path": str(resolved_path),
                "error_code": "not_a_file",
                "error": "The supplied path is not a regular file.",
            }

        raw = resolved_path.read_bytes()
        size_bytes = len(raw)

        try:
            content, encoding = _decode_complete_text(raw)

        except UnicodeDecodeError as exc:
            return {
                "success": False,
                "path": str(resolved_path),
                "error_code": "decoding_error",
                "error": (
                    "The file could not be decoded using the supported "
                    f"encoding rules: {exc}"
                ),
            }
        except ValueError as exc:
            if str(exc) == "unsupported_binary":
                return {
                    "success": False,
                    "path": str(resolved_path),
                    "error_code": "unsupported_file_type",
                    "error": "The file appears to contain binary data.",
                }
            raise

        return {
            "success": True,
            "path": str(resolved_path),
            "content": content,
            "encoding": encoding,
            "size_bytes": size_bytes,
            "total_lines": len(content.splitlines()),
            "content_complete": True,
        }

    except FileNotFoundError:
        return {
            "success": False,
            "path": str(resolved_path),
            "error_code": "not_found",
            "error": "The file no longer exists.",
        }

    except PermissionError:
        return {
            "success": False,
            "path": str(resolved_path),
            "error_code": "permission_denied",
            "error": "Permission denied while reading the file.",
        }

    except IsADirectoryError:
        return {
            "success": False,
            "path": str(resolved_path),
            "error_code": "not_a_file",
            "error": "The supplied path is a directory.",
        }

    except MemoryError:
        return {
            "success": False,
            "path": str(resolved_path),
            "error_code": "resource_exhausted",
            "error": "Insufficient memory to read the complete file.",
        }

    except OSError as exc:
        return {
            "success": False,
            "path": str(resolved_path),
            "error_code": "io_error",
            "error": str(exc),
        }


@tool(args_schema=ReadFileInput)
async def read_file(path: str) -> dict:
    """
    Read the complete contents of a text file.

    No line, character, or file-size truncation is applied.
    Binary and undecodable files return explicit errors.
    """

    return await asyncio.to_thread(
        _read_file_sync,
        path,
        get_workspace_root(),
    )

def _get_file_info_sync(
    path: str,
    workspace_root: Path | None = None,
) -> dict:
    """
    Synchronous implementation of get_file_info.
    """

    try:
        resolved_path = resolve_location(path, workspace_root)

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


@tool(args_schema=GetFileInfoInput)
async def get_file_info(
    path: str,
) -> dict:
    """
    Retrieve filesystem metadata asynchronously.
    """

    return await asyncio.to_thread(_get_file_info_sync, path, get_workspace_root())
