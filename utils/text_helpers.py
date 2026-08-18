from pathlib import Path
from typing import Optional
import shutil

DEFAULT_ENCODING = "utf-8"

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

# ------------------------------------------------------------
# Read limits
#
# These are capability-owned limits.
# The model must never be able to override them.
# ------------------------------------------------------------

MAX_READ_LINES = 400
MAX_READ_CHARS = 60_000


def is_binary_file(path: Path) -> bool:
    """
    Return True if the file appears to be binary.

    Reads only a small sample of the file.
    """

    try:
        with path.open("rb") as f:
            chunk = f.read(1024)

        return b"\x00" in chunk

    except Exception:
        return True


def safe_read_text(
    path: Path,
    encoding: str = DEFAULT_ENCODING,
    max_lines: int = MAX_READ_LINES,
) -> Optional[str]:

    if not path.exists():
        return None

    if not path.is_file():
        return None

    if path.stat().st_size > MAX_FILE_SIZE:
        return None

    if is_binary_file(path):
        return None

    try:

        with path.open(
            "r",
            encoding=encoding,
            errors="replace",
        ) as f:

            lines = []

            for i, line in enumerate(f):

                if i >= max_lines:
                    break

                lines.append(line)

            return "".join(lines)

    except Exception:

        return None


def read_lines(
    path: Path,
    start_line: int = 1,
    encoding: str = DEFAULT_ENCODING,
) -> Optional[dict]:
    """
    Read a bounded window of lines from a text file.

    The caller controls only the starting line.

    The capability itself enforces MAX_READ_LINES and
    MAX_READ_CHARS.

    Lines are 1-indexed.

    The function also determines the total number of lines
    so that callers can paginate deterministically.
    """

    if start_line < 1:
        return None

    if not path.exists():
        return None

    if not path.is_file():
        return None

    if path.stat().st_size > MAX_FILE_SIZE:
        return None

    if is_binary_file(path):
        return None

    try:
        collected_lines: list[str] = []

        total_lines = 0
        collected_chars = 0

        truncated_by_lines = False
        truncated_by_chars = False

        with path.open(
            "r",
            encoding=encoding,
            errors="replace",
        ) as file:

            for line_number, line in enumerate(
                file,
                start=1,
            ):

                total_lines = line_number

                # Ignore lines before the requested starting point.
                if line_number < start_line:
                    continue

                # Once the line limit has been reached, we still
                # continue through the file so total_lines remains
                # accurate.
                if len(collected_lines) >= MAX_READ_LINES:
                    truncated_by_lines = True
                    continue

                # Protect the observation from very large lines.
                remaining_chars = (
                    MAX_READ_CHARS - collected_chars
                )

                if remaining_chars <= 0:
                    truncated_by_chars = True
                    continue

                # Keep complete lines intact whenever possible.
                if len(line) <= remaining_chars:
                    collected_lines.append(line)
                    collected_chars += len(line)
                    continue

                # The next complete line would exceed the character
                # budget. Do not split the line because that would
                # make line-based pagination ambiguous.
                truncated_by_chars = True

        lines_returned = len(collected_lines)

        actual_end_line = (
            start_line + lines_returned - 1
            if lines_returned > 0
            else None
        )

        has_more = (
            actual_end_line is not None
            and actual_end_line < total_lines
        )

        next_start_line = (
            actual_end_line + 1
            if has_more
            else None
        )

        if truncated_by_lines:
            truncation_reason = "line_limit"

        elif truncated_by_chars:
            truncation_reason = "character_limit"

        else:
            truncation_reason = None

        remaining_lines = (
            max(total_lines - actual_end_line, 0)
            if actual_end_line is not None
            else max(total_lines - start_line + 1, 0)
        )

        return {
            "start_line": start_line,
            "end_line": actual_end_line,
            "lines_returned": lines_returned,
            "total_lines": total_lines,
            "remaining_lines": remaining_lines,
            "has_more": has_more,
            "next_start_line": next_start_line,
            "truncation_reason": truncation_reason,
            "content": "".join(collected_lines),
        }

    except (PermissionError, OSError, UnicodeError):
        return None


def find_search_backend() -> str:
    """
    Detect the best available text search backend.

    Priority:
        1. ripgrep
        2. grep
        3. python
    """

    if shutil.which("rg"):
        return "ripgrep"

    # if shutil.which("grep"):
    #     return "grep"

    return "python"