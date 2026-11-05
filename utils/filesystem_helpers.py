from pathlib import Path
from collections.abc import Callable, Iterator

# Default exclusion patterns for generated/dependency/system directories
DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    "*.egg-info",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    ".coverage",
    "htmlcov",
    ".tox",
    ".nox",
    "site-packages",
    "lib/python*",
    "Lib/site-packages",
    "__pypackages__",
    ".gradle",
    "gradle",
    "out",
    "bin",
    "obj",
    "Debug",
    "Release",
    "x64",
    "x86",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dll",
    "*.exe",
    "*.class",
    "*.jar",
    "*.war",
    "*.ear",
    ".next",
    ".nuxt",
    ".output",
    ".vercel",
    ".netlify",
    "vendor",
    "vendor/bundle",
    "bower_components",
    "jspm_packages",
    "typings",
    ".sass-cache",
    ".cache",
    ".parcel-cache",
    ".eslintcache",
    ".stylelintcache",
}


def is_hidden(path: Path) -> bool:
    """
    Return True if a file or directory should be considered hidden.
    """
    return path.name.startswith(".")


def is_excluded(path: Path, exclude_patterns: set[str] | None = None) -> bool:
    """
    Return True if a path should be excluded from traversal.

    Checks both exact name matches and glob patterns.
    """
    patterns = exclude_patterns or DEFAULT_EXCLUDE_DIRS
    name = path.name

    for pattern in patterns:
        if pattern.startswith("*."):
            # Extension pattern like *.pyc
            if name.endswith(pattern[1:]):
                return True
        elif pattern.endswith("*"):
            # Prefix pattern like lib/python*
            if name.startswith(pattern[:-1]):
                return True
        elif name == pattern:
            return True

    return False


def safe_walk(
    root: Path,
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: int | None = None,
    exclude_patterns: set[str] | None = None,
    *,
    skip_symlinks: bool = False,
    on_error: Callable[[Path, OSError], None] | None = None,
    on_symlink: Callable[[Path], None] | None = None,
    on_depth_limit: Callable[[Path], None] | None = None,
) -> Iterator[Path]:
    """
    Incrementally traverse a directory.

    Yields Path objects without eagerly materializing directory contents.

    Optional callbacks allow callers to observe incomplete traversal:
    - on_error: called when a directory or entry cannot be inspected.
    - on_symlink: called when a symbolic link is encountered and skipped.
    - on_depth_limit: called when a directory is found beyond the
      permitted traversal depth.

    Symlinks are skipped only when skip_symlinks=True. This preserves
    the existing behavior for callers that do not opt into that policy.
    """

    def report_error(path: Path, exc: OSError) -> None:
        if on_error is not None:
            on_error(path, exc)

    def walk(directory: Path, depth: int) -> Iterator[Path]:
        try:
            entries = iter(directory.iterdir())
        except OSError as exc:
            report_error(directory, exc)
            return

        while True:
            try:
                entry = next(entries)
            except StopIteration:
                break
            except OSError as exc:
                report_error(directory, exc)
                break

            try:
                is_symlink = entry.is_symlink()
            except OSError as exc:
                report_error(entry, exc)
                continue

            if is_symlink and skip_symlinks:
                if on_symlink is not None:
                    on_symlink(entry)
                continue

            if not include_hidden and is_hidden(entry):
                continue

            if is_excluded(entry, exclude_patterns):
                continue

            yield entry

            if not recursive:
                continue

            if is_symlink:
                continue

            try:
                is_directory = entry.is_dir()
            except OSError as exc:
                report_error(entry, exc)
                continue

            if not is_directory:
                continue

            if max_depth is not None and depth >= max_depth:
                if on_depth_limit is not None:
                    try:
                        boundary_entries = iter(entry.iterdir())

                        while True:
                            try:
                                child = next(boundary_entries)
                            except StopIteration:
                                break
                            except OSError as exc:
                                report_error(entry, exc)
                                break

                            try:
                                child_is_symlink = child.is_symlink()
                            except OSError as exc:
                                report_error(child, exc)
                                continue

                            if skip_symlinks and child_is_symlink:
                                if on_symlink is not None:
                                    on_symlink(child)
                                continue

                            if not include_hidden and is_hidden(child):
                                continue

                            if is_excluded(child, exclude_patterns):
                                continue

                            on_depth_limit(entry)
                            break
                    except OSError as exc:
                        report_error(entry, exc)

                continue

            yield from walk(entry, depth + 1)

    yield from walk(root, 1)