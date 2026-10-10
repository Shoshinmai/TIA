import string
from pathlib import Path

# ---------------------------------------------------------------------------
# Location aliases understood by the planner.
# ---------------------------------------------------------------------------

LOCATION_ALIASES = {
    "my desktop": "desktop",
    "desktop folder": "desktop",

    "my downloads": "downloads",
    "download folder": "downloads",

    "current project": "project",
    "project root": "project",

    "working directory": "current directory",
    "current folder": "current directory",
}

# Module-level workspace root for tool access (thread-local fallback).
# Set by task_initializer at the start of each run.
_WORKSPACE_ROOT: Path | None = None


def set_workspace_root(path: str | Path) -> None:
    """Set the workspace root for location resolution."""
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = Path(path).resolve() if path else None


def get_workspace_root() -> Path | None:
    """Get the current workspace root."""
    return _WORKSPACE_ROOT


def is_drive_root(path: Path) -> bool:
    """
    Check if a path is a Windows drive root (e.g., C:\\, D:\\).
    """
    try:
        resolved = path.resolve()
        # On Windows, drive roots have no parent beyond the drive letter
        return len(resolved.parts) == 1 and resolved.drive == str(resolved)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_location(location: str) -> str:
    """
    Normalize a planner supplied location.

    Example:
        " My Desktop "
            -> "desktop"

        "Desktop Folder"
            -> "desktop"
    """

    normalized = location.strip().lower()

    return LOCATION_ALIASES.get(normalized, normalized)


# ---------------------------------------------------------------------------
# User folders
# ---------------------------------------------------------------------------

def get_user_locations() -> dict[str, Path]:
    """
    Returns common user folders that exist on the current machine.
    """

    home = Path.home()

    folders = {}

    candidates = {
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
        "pictures": home / "Pictures",
        "videos": home / "Videos",
        "music": home / "Music",
        "home": home,
    }

    for name, path in candidates.items():

        if path.exists():
            folders[name] = path

    return folders


# ---------------------------------------------------------------------------
# Available drives
# ---------------------------------------------------------------------------

def get_available_drives() -> dict[str, Path]:
    """
    Detect available Windows drives.

    Example:
        C drive
        D drive
        E drive
    """

    drives = {}

    for letter in string.ascii_uppercase:

        drive = Path(f"{letter}:\\")

        if drive.exists():

            drives[f"{letter.lower()} drive"] = drive
            drives[f"{letter}:"] = drive
            drives[letter.lower()] = drive

    return drives


# ---------------------------------------------------------------------------
# Search locations
# ---------------------------------------------------------------------------

def get_search_locations(
    current_directory: Path | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Path]:
    """
    Build the planner-visible location map.
    """

    if current_directory is None:
        current_directory = Path.cwd()

    locations = {
        "current directory": current_directory,
    }

    # Use workspace root if provided, otherwise fall back to module-level, then current_directory
    effective_workspace = workspace_root or get_workspace_root() or current_directory
    locations["workspace"] = effective_workspace
    locations["project"] = effective_workspace

    locations.update(get_user_locations())
    locations.update(get_available_drives())

    return locations


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------

def resolve_location(
    location: str,
    current_directory: Path | None = None,
    workspace_root: Path | None = None,
    allow_drive_root: bool = False,
) -> Path:
    """
    Resolve a planner supplied location into a filesystem Path.

    Supports

    • Natural language locations
    • Absolute paths
    • Relative paths

    Raises:
        ValueError: If location is a drive root and allow_drive_root is False.
    """

    if current_directory is None:
        current_directory = Path.cwd()

    normalized = normalize_location(location)

    # Use explicit workspace_root if provided, otherwise fall back to module-level
    effective_workspace_root = workspace_root or get_workspace_root()
    locations = get_search_locations(current_directory, effective_workspace_root)

    # Planner keywords
    if normalized in locations:
        return locations[normalized]

    candidate = Path(location)

    # Absolute path
    if candidate.is_absolute():

        # Gate drive-root searches
        if not allow_drive_root and is_drive_root(candidate):
            raise ValueError(
                f"Drive-root search not allowed: '{location}'. "
                "Use a specific subdirectory or enable allow_drive_root."
            )

        if candidate.exists():
            return candidate

        raise ValueError(f"Location does not exist: {location}")

    # Relative path
    candidate = (current_directory / candidate).resolve()

    if candidate.exists():
        return candidate

    raise ValueError(f"Unknown location: {location}")