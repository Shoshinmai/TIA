from pathlib import Path
from collections.abc import Iterator

def is_hidden(path: Path) -> bool:
    """
    Return True if a file or directory should be considered hidden.
    """
    return path.name.startswith(".")

def safe_walk(
    root: Path,
    recursive: bool = False,
    include_hidden: bool = False,
    max_depth: int | None = None,
) -> Iterator[Path]:
    """
    Safely traverse a directory.

    Yields Path objects.

    Supports:

    - recursive traversal
    - maximum recursion depth
    - hidden file filtering

    Does not follow symbolic links.
    """
    if not recursive:

        for entry in root.iterdir():

            if not include_hidden and is_hidden(entry):
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
            yield entry
    
            if entry.is_dir() and not entry.is_symlink():
                try:
                    yield from walk(entry, depth + 1)
                except (PermissionError, OSError):
                    continue
    yield from walk(root, 1)