from enum import StrEnum


class RuntimeStage(StrEnum):
    """
    High-level runtime subsystems.

    The dispatcher maps RuntimeMode -> RuntimeStage.

    The Runtime Kernel later maps RuntimeStage -> graph node.
    """

    PLANNER = "planner"

    EXECUTOR = "executor"

    CRITIC = "critic"

    TERMINATE = "terminate"

    ERROR = "error"