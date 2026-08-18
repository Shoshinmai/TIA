from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Any

class ResourceType(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    URL = "url"
    PROCESS = "process"
    OTHER = "other"

class Resource(BaseModel):
    """
    A resource discovered during task execution.
    """

    type: ResourceType = Field(
        description="Resource type (file, directory, url, process, etc.)"
    )

    identifier: str = Field(
        description="Unique identifier or path."
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured metadata."
    )
    
class Fact(BaseModel):
    """
    Structured knowledge extracted from a tool result.
    """

    statement: str

    # confidence: float = Field(
    #     default=1.0,
    #     ge=0.0,
    #     le=1.0
    # )

    source: str
    
class SignalType(StrEnum):
    NO_PROGRESS = "no_progress"
    RETRY_RECOMMENDED = "retry_recommended"
    RESULT_TRUNCATED = "result_truncated"
    REPLAN_REQUIRED = "replan_required"    

class Signal(BaseModel):
    """
    Planner-relevant signal.
    """

    name: SignalType

    value: Any = None

    reason: str | None = None
    
class ExecutionOutcome(BaseModel):
    """
    Semantic outcome of one capability execution.

    This contains execution-level evidence that downstream
    runtime components may rely on.
    """

    success: bool

    progress_made: bool

    message: str | None = None

    return_code: int | None = None

    stdout: str = ""

    stderr: str = ""
    
class ArtifactCandidate(BaseModel):
    """
    Candidate artifact produced by a tool.
    """

    artifact_type: str

    summary: str

    data: Any
    
class ToolExecutionContext(BaseModel):
    """
    Metadata describing the execution that produced this result.
    """

    tool_name: str

    attempt: int = Field(
        default=1,
        ge=1,
    )
    
class NormalizedResult(BaseModel):
    """
    Semantic representation of a tool result.
    """

    context: ToolExecutionContext

    resources: list[Resource] = Field(default_factory=list)

    facts: list[Fact] = Field(default_factory=list)

    # signals: list[Signal] = Field(default_factory=list)

    execution: ExecutionOutcome

    artifact: ArtifactCandidate | None = None
    
class MemoryUpdateProposal(BaseModel):
    """
    Proposed updates to runtime memory.
    """

    known_facts: list[Fact] = Field(default_factory=list)

    discovered_resources: list[Resource] = Field(default_factory=list)

    completed_work: list[str] = Field(default_factory=list)

    unresolved_needs: list[str] = Field(default_factory=list)

    evidence: list[str] = Field(default_factory=list)

class ArtifactAction(StrEnum):
    STORE = "store"
    SKIP = "skip"


class ArtifactDecision(BaseModel):
    """
    Final artifact storage decision.
    """

    action: ArtifactAction

    reason: str

    artifact: ArtifactCandidate | None = None
    
class RuntimeProcessingResult(BaseModel):
    """
    Output of the Runtime Processing Pipeline.

    This object contains everything required to update runtime memory.
    It intentionally does not mutate state itself.
    """

    normalized_result: NormalizedResult

    artifact_decision: ArtifactDecision

    memory_update: MemoryUpdateProposal