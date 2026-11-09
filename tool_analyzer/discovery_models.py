
from __future__ import annotations

from pydantic import BaseModel, Field

from models import SearchFileMatch


class DiscoveryDirectoryGroup(BaseModel):
    """A directory containing one or more returned search matches.

    match_count counts matching files directly inside this directory,
    not files in descendant directories.
    """

    directory: str = Field(
        min_length=1,
        description=(
            "Directory path relative to the search root. "
            "Use '.' for files directly inside the search root."
        ),
    )

    match_count: int = Field(
        ge=1,
        description="Number of returned matching files directly in this directory.",
    )


class DiscoveryAnalysis(BaseModel):
    """Compact, deterministic representation of a search_files result.

    This model is intended for the Main Agent's observation context.
    The original search result remains preserved separately in ArtifactStore.
    """

    success: bool = Field(
        description="Whether the original search operation succeeded."
    )

    query: str = Field(
        description="Original normalized search query."
    )

    root: str | None = Field(
        default=None,
        description="Resolved absolute search root.",
    )

    disclosed_paths: list[SearchFileMatch] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Top 10 search matches, preserving their original ranking "
            "and match metadata."
        ),
    )

    directory_groups: list[DiscoveryDirectoryGroup] = Field(
        default_factory=list,
        description=(
            "Compressed directory representation of all returned matches. "
            "Groups are ordered by the first occurrence of each directory "
            "in the original ranked results."
        ),
    )

    returned_count: int = Field(
        default=0,
        ge=0,
        description="Number of matches returned by the original search.",
    )

    undisclosed_returned_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Number of returned matches not included in disclosed_paths."
        ),
    )

    total_matches: int = Field(
        default=0,
        ge=0,
        description=(
            "Matches found in the traversed search space. "
            "Exact only when complete is true."
        ),
    )

    complete: bool = Field(
        description="Whether the original eligible search space was fully traversed."
    )

    truncated: bool = Field(
        default=False,
        description="Whether the original search result was truncated."
    )

    limit_reached: str | None = Field(
        default=None,
        description="Original search limit or traversal stopping reason."
    )

    traversal_errors: list[str] = Field(
        default_factory=list,
        description="Filesystem traversal errors reported by the original search.",
    )

    skipped_symlinks: int = Field(
        default=0,
        ge=0,
        description="Number of symlinks skipped by the original search.",
    )

    error: str | None = Field(
        default=None,
        description="Original search error, if any.",
    )

    source_artifact_id: str | None = Field(
        default=None,
        description="Artifact reference to the complete original search result.",
    )
