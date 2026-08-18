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
) -> dict[str, Path]:
    """
    Build the planner-visible location map.
    """

    if current_directory is None:
        current_directory = Path.cwd()

    locations = {
        "workspace": current_directory,
        "project": current_directory,
        "current directory": current_directory,
    }

    locations.update(get_user_locations())
    locations.update(get_available_drives())

    return locations


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------

def resolve_location(
    location: str,
    current_directory: Path | None = None,
) -> Path:
    """
    Resolve a planner supplied location into a filesystem Path.

    Supports

    • Natural language locations
    • Absolute paths
    • Relative paths

    Raises:
        ValueError
    """

    if current_directory is None:
        current_directory = Path.cwd()

    normalized = normalize_location(location)

    locations = get_search_locations(current_directory)

    # Planner keywords
    if normalized in locations:
        return locations[normalized]

    candidate = Path(location)

    # Absolute path
    if candidate.is_absolute():

        if candidate.exists():
            return candidate

        raise ValueError(f"Location does not exist: {location}")

    # Relative path
    candidate = (current_directory / candidate).resolve()

    if candidate.exists():
        return candidate

    raise ValueError(f"Unknown location: {location}")