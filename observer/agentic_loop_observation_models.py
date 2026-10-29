from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


MAX_OBSERVATION_CHARS = 10_000
MAX_OBSERVATIONS_PER_CONTEXT = 20


class ObservationSource(StrEnum):
    """Origin of a factual observation."""

    CAPABILITY = "capability"
    RUNTIME = "runtime"
    USER = "user"
    OTHER = "other"


class ToolExecutionOutcome(StrEnum):
    """What happened when a capability was dispatched."""

    RETURNED = "returned"
    RAISED_EXCEPTION = "raised_exception"
    NOT_ATTEMPTED = "not_attempted"


class ResultCompleteness(StrEnum):
    """What is known about the completeness of the returned source result."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class ToolResultStorageStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    STORED = "stored"
    FAILED = "failed"


class ToolResultRecord(BaseModel):
    """Source record for one capability attempt.

    raw_result preserves the result returned by the capability. It is not
    the bounded observation shown to the agent. Persistent artifact-backed
    storage is a later implementation step.
    """

    sequence: int = Field(ge=1)
    tool_name: str = Field(min_length=1, max_length=200)
    action_signature: str | None = Field(default=None, max_length=200)

    outcome: ToolExecutionOutcome
    completeness: ResultCompleteness = ResultCompleteness.UNKNOWN

    storage_status: ToolResultStorageStatus = ToolResultStorageStatus.NOT_APPLICABLE
    artifact_id: str | None = Field(default=None, min_length=1)
    storage_error: str | None = Field(default=None, max_length=2_000)

    # Retain the payload in state only if storage fails, so a failed save
    # doesn't silently discard the original result.
    raw_result: Any = None
    error_message: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome == ToolExecutionOutcome.RAISED_EXCEPTION:
            if not self.error_message or not self.error_message.strip():
                raise ValueError("RAISED_EXCEPTION requires a non-empty error_message.")
            if self.completeness != ResultCompleteness.UNAVAILABLE:
                raise ValueError(
                    "A result unavailable because execution raised an "
                    "exception must use UNAVAILABLE completeness."
                )

        elif self.outcome == ToolExecutionOutcome.NOT_ATTEMPTED:
            if self.completeness != ResultCompleteness.UNAVAILABLE:
                raise ValueError(
                    "A result for an action that was not attempted must "
                    "use UNAVAILABLE completeness."
                )

        elif self.outcome == ToolExecutionOutcome.RETURNED:
            if self.error_message is not None:
                raise ValueError(
                    "A normally returned result must not have error_message."
                )

            if self.storage_status == ToolResultStorageStatus.STORED:
                if not self.artifact_id:
                    raise ValueError("STORED results require an artifact_id.")
                if self.storage_error is not None:
                    raise ValueError("STORED results must not have storage_error.")

            elif self.storage_status == ToolResultStorageStatus.FAILED:
                if self.artifact_id is not None:
                    raise ValueError("A failed save must not publish an artifact_id.")
                if not self.storage_error:
                    raise ValueError("FAILED storage requires storage_error.")

            elif self.artifact_id is not None:
                raise ValueError("An artifact_id requires successful storage.")

        else:
            if self.storage_status != ToolResultStorageStatus.NOT_APPLICABLE:
                raise ValueError(
                    "Storage is not applicable when no result was returned."
                )
            if self.artifact_id is not None:
                raise ValueError("A non-returned result cannot have an artifact_id.")

        return self


class ObservationRecord(BaseModel):
    """Bounded account of what happened, linked to its source result if any.

    Observations report evidence and limitations. They do not store critic
    advice or replace the original tool result.
    """

    sequence: int = Field(ge=1)
    source: ObservationSource
    source_name: str = Field(default="", max_length=200)
    action_signature: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_OBSERVATION_CHARS)

    # Links to ToolResultRecord.sequence. None is appropriate for runtime
    # events that do not originate from a capability result.
    tool_result_sequence: int | None = Field(default=None, ge=1)

    # This describes truncation of the observation text, not completeness
    # of the original result.
    content_truncated: bool = False
    artifact_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if not self.content.strip():
            raise ValueError("Observation content must not be blank.")
        return self
