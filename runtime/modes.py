"""
Runtime execution modes.

The Runtime Kernel is always in exactly one mode.
Modes represent orchestration state, not implementation details.
"""

from enum import StrEnum


class RuntimeMode(StrEnum):
    """
    High-level runtime lifecycle.
    """

    INITIALIZING = "initializing"

    PLANNING = "planning"

    EXECUTING = "executing"

    REVIEWING = "reviewing"

    FINISHED = "finished"

    ERROR = "error"
    
_TERMINAL_MODES = {
    RuntimeMode.FINISHED,
    RuntimeMode.ERROR,
}


def is_terminal_mode(mode: RuntimeMode) -> bool:
    return mode in _TERMINAL_MODES


def can_execute(mode: RuntimeMode) -> bool:
    return mode == RuntimeMode.EXECUTING


def requires_planning(mode: RuntimeMode) -> bool:
    return mode == RuntimeMode.PLANNING


def requires_review(mode: RuntimeMode) -> bool:
    return mode == RuntimeMode.REVIEWING