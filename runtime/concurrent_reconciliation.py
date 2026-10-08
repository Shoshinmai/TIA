from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConcurrentReconciliationResult:
    """
    Deterministic summary of one completed concurrent
    execution-wave reconciliation.

    The reconciliation result is descriptive only.

    It does not own or mutate:
    - TaskPlan
    - ExecutionMemory
    - artifact_references

    Those remain owned by their respective managers/state
    boundaries.

    This object allows the coordinator to know exactly what the
    central reconciler incorporated from one execution wave.
    """

    wave_task_ids: list[str] = field(
        default_factory=list,
    )

    reconciled_task_ids: list[str] = field(
        default_factory=list,
    )

    newly_ready_task_ids: list[str] = field(
        default_factory=list,
    )

    blocked_task_ids: list[str] = field(
        default_factory=list,
    )

    merged_attempt_ids: list[str] = field(
        default_factory=list,
    )

    persisted_artifact_ids: list[str] = field(
        default_factory=list,
    )