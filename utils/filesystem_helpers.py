from pathlib import Path
from collections.abc import Iterator

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
) -> Iterator[Path]:
    """
    Safely traverse a directory.

    Yields Path objects.

    Supports:

    - recursive traversal
    - maximum recursion depth
    - hidden file filtering
    - exclusion patterns for generated/dependency directories

    Does not follow symbolic links.
    """
    if not recursive:

        for entry in root.iterdir():

            if not include_hidden and is_hidden(entry):
                continue

            if is_excluded(entry, exclude_patterns):
                continue

            yield entry
        return

    def walk(directory: Path, depth: int):
        
        if max_depth is not None and depth > max_depth:
            return
        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError):
            return
        for entry in entries:
            if not include_hidden and is_hidden(entry):
                continue

            if is_excluded(entry, exclude_patterns):
                continue

            yield entry
    
            if entry.is_dir() and not entry.is_symlink():
                try:
                    yield from walk(entry, depth + 1)
                except (PermissionError, OSError):
                    continue
    yield from walk(root, 1)