from collections.abc import Callable
from typing import TypeVar

from agents.terminal.result_processing.models import (
    Fact,
    MemoryUpdateProposal,
    Resource,
)
from agents.terminal.state import TerminalState


T = TypeVar("T")


# ============================================================
# Text Normalization
# ============================================================

def _normalize_text(value: str) -> str:
    """
    Normalize text for deterministic duplicate detection.

    This does NOT rewrite the stored value.

    It only normalizes the comparison key.
    """

    return " ".join(value.strip().lower().split())


# ============================================================
# Generic Unique Append
# ============================================================

def append_unique(
    target: list[T],
    incoming: list[T],
    key: Callable[[T], object],
) -> None:
    """
    Append only items whose normalized key does not already exist.
    """

    existing = {
        key(item)
        for item in target
    }

    for item in incoming:
        identifier = key(item)

        if identifier not in existing:
            target.append(item)
            existing.add(identifier)


# ============================================================
# Memory Quality Guards
# ============================================================

_EXECUTION_NOISE_PREFIXES = (
    "command executed",
    "executed command",
    "ran ",
    "run ",
    "executed ",
    "attempted to execute",
    "attempted to run",
    "attempted ",
    "tool executed",
    "tool returned",
    "tool call",
    "exit code",
    "return code",
    "command failed",
    "command succeeded",
    "execution failed",
    "execution succeeded",
)


_ACTION_PREFIXES = (
    "search for ",
    "search ",
    "find ",
    "look for ",
    "read ",
    "inspect ",
    "open ",
    "run ",
    "execute ",
    "try ",
    "retry ",
    "use ",
    "check ",
    "locate ",
    "look up ",
)


def _is_execution_noise(value: str) -> bool:
    """
    Detect statements that describe execution mechanics rather than
    durable task knowledge.
    """

    normalized = _normalize_text(value)

    return normalized.startswith(
        _EXECUTION_NOISE_PREFIXES
    )


def _is_action_instruction(value: str) -> bool:
    """
    Detect action-oriented text.

    Active Task Memory must contain knowledge, not instructions
    for the next action.
    """

    normalized = _normalize_text(value)

    return normalized.startswith(
        _ACTION_PREFIXES
    )


def _is_valid_fact(fact: Fact) -> bool:
    """
    Deterministically reject obvious execution-log noise.

    The LLM condenser remains responsible for semantic extraction.
    This is only a safety boundary.
    """

    statement = fact.statement.strip()

    if not statement:
        return False

    if _is_execution_noise(statement):
        return False

    if _is_action_instruction(statement):
        return False

    return True


def _is_valid_completed_work(value: str) -> bool:
    """
    Completed work must describe a completed milestone rather than
    an execution event or future action.
    """

    value = value.strip()

    if not value:
        return False

    if _is_execution_noise(value):
        return False

    if _is_action_instruction(value):
        return False

    return True


def _is_valid_unresolved_need(value: str) -> bool:
    """
    An unresolved need must describe missing information.

    It must not be phrased as an instruction to perform an action.
    """

    value = value.strip()

    if not value:
        return False

    if _is_action_instruction(value):
        return False

    return True


def _is_valid_resource(resource: Resource) -> bool:
    """
    Reject malformed or unresolved resource identifiers.

    In particular, unresolved tool-output placeholders must never
    enter Active Task Memory.
    """

    identifier = resource.identifier.strip()

    if not identifier:
        return False

    # Reject unresolved template expressions such as:
    #
    # ${search_files.result[0].path}
    #
    # {search_files.result[0].path}
    #
    if "${" in identifier:
        return False

    if "{" in identifier and "}" in identifier:
        return False

    return True


# ============================================================
# State Mutation
# ============================================================

def mutate_state(
    state: TerminalState,
    proposal: MemoryUpdateProposal,
) -> None:
    """
    Apply a MemoryUpdateProposal to ActiveTaskMemory.

    This is the deterministic memory mutation boundary.

    Responsibilities
    ----------------
    - Validate basic memory quality constraints.
    - Prevent duplicate entries.
    - Reject execution-log noise.
    - Reject action instructions.
    - Reject malformed resource references.
    - Leave all other runtime state untouched.

    The State Mutator does NOT perform semantic reasoning.
    """

    active_memory = state.get(
        "active_memory",
    )

    if active_memory is None:
        raise ValueError(
            "Cannot mutate memory because TerminalState does not "
            "contain active_memory."
        )

    # ========================================================
    # Completed Work
    # ========================================================

    valid_completed_work = [
        item
        for item in proposal.completed_work
        if _is_valid_completed_work(item)
    ]

    append_unique(
        target=active_memory.completed_work,
        incoming=valid_completed_work,
        key=_normalize_text,
    )

    # ========================================================
    # Unresolved Needs
    # ========================================================

    valid_unresolved_needs = [
        item
        for item in proposal.unresolved_needs
        if _is_valid_unresolved_need(item)
    ]

    append_unique(
        target=active_memory.unresolved_needs,
        incoming=valid_unresolved_needs,
        key=_normalize_text,
    )

    # ========================================================
    # Discovered Resources
    # ========================================================

    valid_resources = [
        resource
        for resource in proposal.discovered_resources
        if _is_valid_resource(resource)
    ]

    append_unique(
        target=active_memory.discovered_resources,
        incoming=valid_resources,
        key=lambda resource: (
            str(resource.type).lower(),
            _normalize_text(resource.identifier),
        ),
    )

    # ========================================================
    # Known Facts
    # ========================================================

    valid_facts = [
        fact
        for fact in proposal.known_facts
        if _is_valid_fact(fact)
    ]

    append_unique(
        target=active_memory.known_facts,
        incoming=valid_facts,
        key=lambda fact: _normalize_text(
            fact.statement,
        ),
    )