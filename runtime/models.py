from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .events import RuntimeEvent
from .modes import RuntimeMode


class RuntimeEvidence(BaseModel):
    """
    Runtime-neutral evidence supporting a runtime decision.
    """

    source: str = Field(
        min_length=1,
    )

    observation: str = Field(
        min_length=1,
    )


class RuntimeDecisionContext(BaseModel):
    """
    Context attached to a runtime decision.

    This preserves the semantic feedback produced by a
    decision-making subsystem without coupling the runtime
    to that subsystem's internal models.
    """

    rationale: str = Field(
        min_length=1,
    )

    evidence: list[RuntimeEvidence] = Field(
        min_length=1,
    )


class RuntimeState(BaseModel):
    """
    Represents the current state of the Terminal Agent runtime.

    The Runtime Kernel is the sole owner of this model.
    """

    mode: RuntimeMode = RuntimeMode.INITIALIZING

    last_event: RuntimeEvent | None = None

    iteration: int = 0

    started_at: datetime = Field(
        default_factory=datetime.utcnow,
    )
    
    decision_context: RuntimeDecisionContext | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class RuntimeSnapshot(BaseModel):
    """
    Read-only snapshot of the runtime state.
    """

    mode: RuntimeMode

    last_event: RuntimeEvent | None

    iteration: int


def snapshot_runtime(
    runtime_state: RuntimeState,
) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        mode=runtime_state.mode,
        last_event=runtime_state.last_event,
        iteration=runtime_state.iteration,
    )