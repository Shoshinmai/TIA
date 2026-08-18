"""
Resource ranking utilities.

The Resource Ranker prioritizes discovered resources before they
are presented to the Memory Condenser.

Ranking is deterministic and completely side-effect free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agents.terminal.result_processing.models import Resource, ResourceType


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

TOOL_CONFIDENCE = {
    "read_file": 40,
    "search_files": 30,
    "search_content": 30,
    "search_artifact": 25,
    "list_directory": 10,
}


FILE_BONUS = 20
DIRECTORY_BONUS = 10

EXACT_MATCH_BONUS = 120
PARTIAL_MATCH_BONUS = 40
PATH_MATCH_BONUS = 15

MATCHED_QUERY_BONUS = 150
MAX_DEPTH_BONUS = 20


_WORD_PATTERN = re.compile(r"[A-Za-z0-9_]+")


# ---------------------------------------------------------
# Models
# ---------------------------------------------------------

@dataclass(slots=True)
class RankedResource:
    resource: Resource
    score: int


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def _normalize_identifier(identifier: str) -> str:
    """
    planner.py -> planner
    graph_builder.py -> graph_builder
    """

    identifier = identifier.replace("\\", "/")
    identifier = identifier.split("/")[-1]

    if "." in identifier:
        identifier = identifier.rsplit(".", 1)[0]

    return identifier.lower()


def _extract_keywords(text: str) -> set[str]:

    return {
        token.lower()
        for token in _WORD_PATTERN.findall(text)
        if len(token) > 2
    }


def _score_resource(
    *,
    goal_keywords: set[str],
    tool_name: str,
    resource: Resource,
) -> int:

    score = 0

    identifier = _normalize_identifier(resource.identifier)

    # --------------------------------------------------
    # Tool confidence
    # --------------------------------------------------

    score += TOOL_CONFIDENCE.get(tool_name, 0)

    # --------------------------------------------------
    # Resource type
    # --------------------------------------------------

    if resource.type == ResourceType.FILE:
        score += FILE_BONUS

    elif resource.type == ResourceType.DIRECTORY:
        score += DIRECTORY_BONUS

    # --------------------------------------------------
    # Goal relevance
    # --------------------------------------------------

    for keyword in goal_keywords:

        if keyword == identifier:
            score += EXACT_MATCH_BONUS

        elif keyword in identifier:
            score += PARTIAL_MATCH_BONUS

        elif keyword in resource.identifier.lower():
            score += PATH_MATCH_BONUS

    # --------------------------------------------------
    # Metadata
    # --------------------------------------------------

    metadata = resource.metadata or {}

    if metadata.get("matched_query"):
        score += MATCHED_QUERY_BONUS

    confidence = metadata.get("confidence")

    if isinstance(confidence, (int, float)):
        score += int(confidence * 50)

    depth = metadata.get("depth")

    if isinstance(depth, int):
        score += max(MAX_DEPTH_BONUS - depth, 0)

    return score


# ---------------------------------------------------------
# Public API
# ---------------------------------------------------------

def rank_resources(
    *,
    goal: str,
    tool_name: str,
    resources: list[Resource],
) -> list[RankedResource]:
    """
    Rank resources according to their relevance.

    No mutation is performed.
    """

    goal_keywords = _extract_keywords(goal)

    ranked = [
        RankedResource(
            resource=resource,
            score=_score_resource(
                goal_keywords=goal_keywords,
                tool_name=tool_name,
                resource=resource,
            ),
        )
        for resource in resources
    ]

    ranked.sort(
        key=lambda item: item.score,
        reverse=True,
    )

    return ranked