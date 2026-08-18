from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field

from agents.terminal.result_processing.models import ExecutionOutcome, Fact, Resource


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TerminalAction(BaseModel):

    action_type: Literal["terminal_command", "artifact_query", "tool_call"]

    thought: str

    command: str = ""

    tool_name: str = ""

    tool_input: str = ""


class EvaluatorDecision(BaseModel):
    decision: Literal["DONE", "CONTINUE"]


class ObservationSummary(BaseModel):
    summary: str


class ObservationDecision(BaseModel):

    memory_strategy: Literal[
        "pass_through", "store_artifact", "store_and_summarize", "discard"
    ]

    artifact_type: Literal[
        "file_listing",
        "package_list",
        "log",
        "git_diff",
        "command_output",
        "system_command",
    ]

    summary: str

    important_information: str

    reasoning: str

    conclusion: str
    # summary: str = Field(min_length=1)

    # important_information: str = ""

    # reasoning: str = Field(min_length=1)

    # conclusion: str = Field(min_length=1)


class ObservationInput(BaseModel):

    source: str

    tool_name: str | None = None

    success: bool

    raw_result: dict | str


class PlanningStep(BaseModel):
    """
    Single planning decision produced by the planner.
    """

    strategy: str = Field(description="High-level strategy for the next step.")

    capability: str = Field(description="Capability selected for execution.")

    args: dict[str, Any] = Field(
        default_factory=dict, description="Arguments for the selected capability."
    )


class PlanningOutput(BaseModel):
    """
    Complete planner response.

    Additional planning metadata can be added later without
    changing the graph contract.
    """

    planning_step: PlanningStep


# ============================================================
# Task Planning Models (Planner Migration)
# ============================================================


class PlannerTask(BaseModel):
    """
    High-level objective produced by the planner.

    PlannerTask represents WHAT should be accomplished.
    It intentionally contains no runtime execution details.
    """

    planner_task_id: str = Field(
        min_length=1,
        description=(
            "Planner-scoped identifier used to reference this task "
            "within the Task Planning output."
        ),
    )

    objective: str = Field(
        min_length=1,
        description=("High-level objective that advances the overall strategy."),
    )

    dependencies: list[str] = Field(
        default_factory=list,
        description=(
            "Planner task identifiers that must be completed before "
            "this objective becomes executable."
        ),
    )


class TaskPlanningOutput(BaseModel):
    """
    Strategic planning output produced by the Planner.

    This model is intentionally independent of the runtime.

    It represents the planner's view of the work to be done.
    A deterministic materialization step later converts this
    structure into a runtime TaskPlan.
    """

    strategy: str = Field(
        min_length=1,
        description="Overall strategy for accomplishing the user's goal.",
    )

    tasks: list[PlannerTask] = Field(
        min_length=1,
        description="Ordered planner objectives.",
    )


class ListDirectoryInput(BaseModel):
    """
    Input schema for listing the contents of a directory.
    """

    location: str = Field(
        default="current directory",
        description=(
            "Directory to inspect. Supports natural language locations "
            "such as current directory, project, desktop, downloads, "
            "documents, pictures, videos, music, C drive, D drive, etc."
        ),
    )

    recursive: bool = Field(
        default=False, description="Whether to recursively traverse subdirectories."
    )

    include_hidden: bool = Field(
        default=False, description="Include hidden files and folders."
    )

    max_depth: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Maximum recursion depth when recursive=True.",
    )


class SearchContentInput(BaseModel):
    """
    Input schema for searching text inside files.
    """

    query: str = Field(description="Text or pattern to search for.")

    location: str = Field(
        default="current directory",
        description=("Natural language search location."),
    )

    file_pattern: str = Field(
        default="*",
        description=("Glob pattern limiting which files are searched."),
    )

    case_sensitive: bool = Field(
        default=False, description="Perform case-sensitive matching."
    )

    max_results: int = Field(
        default=50, ge=1, le=500, description="Maximum number of matching files."
    )


class ReadFileInput(BaseModel):
    """
    Input schema for reading a bounded window of a text file.

    The model may choose where reading begins, but it does not
    control how much content the capability returns.

    The read capability enforces its own line and character
    limits to protect the model context.
    """

    path: str = Field(
        description=(
            "Path of the text file to read. Supports absolute "
            "and relative filesystem paths."
        )
    )

    start_line: int = Field(
        default=1,
        ge=1,
        description=(
            "First line to read. Lines are 1-indexed. "
            "Use the next_start_line returned by a previous "
            "read_file call to continue reading a large file."
        ),
    )


class GetFileInfoInput(BaseModel):
    """
    Input schema for retrieving filesystem metadata about a file
    or directory.
    """

    path: str = Field(
        description=(
            "Path of the file or directory to inspect. "
            "Supports absolute and relative filesystem paths."
        )
    )


class SearchArtifactInput(BaseModel):
    """
    Input schema for searching within a stored artifact.
    """

    artifact_id: str = Field(
        description=("Unique identifier of the artifact to search.")
    )

    query: str = Field(
        min_length=1, description=("Text to search for within the artifact.")
    )

    case_sensitive: bool = Field(
        default=False, description=("Whether matching should respect letter case.")
    )

    max_results: int = Field(
        default=50,
        ge=1,
        le=500,
        description=("Maximum number of matching lines to return."),
    )


class ReadArtifactInput(BaseModel):
    """
    Input schema for reading a bounded window from a stored artifact.
    """

    artifact_id: str = Field(description=("Unique identifier of the artifact to read."))

    start_line: int = Field(
        default=1,
        ge=1,
        description=("First serialized artifact line to read. " "Lines are 1-indexed."),
    )

    max_lines: int = Field(
        default=200,
        ge=1,
        le=1000,
        description=("Maximum number of serialized artifact lines to return."),
    )


class TaskStatus(StrEnum):
    """
    Lifecycle state of a Terminal Agent task.
    """

    CREATED = "created"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    """
    Outcome state of one execution attempt.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MemoryScope(StrEnum):
    """
    Lifetime and visibility scope of stored memory.
    """

    TASK = "task"
    THREAD = "thread"
    PERSISTENT = "persistent"


class MemoryStatus(StrEnum):
    """
    Lifecycle state of a durable memory entry.
    """

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    ARCHIVED = "archived"


class TaskContext(BaseModel):
    """
    Identity and lifecycle information for one
    Terminal Agent task.
    """

    task_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier of the task.",
    )

    thread_id: str = Field(
        description=(
            "Identifier of the conversation or thread " "that owns this task."
        ),
    )

    goal: str = Field(
        min_length=1,
        description=("Original goal assigned to the Terminal Agent."),
    )

    status: TaskStatus = Field(
        default=TaskStatus.CREATED,
        description="Current lifecycle status of the task.",
    )

    created_at: datetime = Field(
        default_factory=utc_now,
        description="UTC timestamp when the task was created.",
    )

    updated_at: datetime = Field(
        default_factory=utc_now,
        description="UTC timestamp of the latest task update.",
    )


class ActiveTaskMemory(BaseModel):
    """
    Structured current knowledge maintained while executing
    one Terminal Agent task.

    This model represents what the agent currently knows about
    the task. It does not store execution history, raw tool
    results, or persistent knowledge.
    """

    known_facts: list[Fact] = Field(
        default_factory=list,
        description=("Task-relevant facts currently known to be true."),
    )

    discovered_resources: list[Resource] = Field(
        default_factory=list,
        description=(
            "Resources discovered while working on the task, "
            "such as files, directories, processes, commands, "
            "URLs, or other task-relevant entities."
        ),
    )

    completed_work: list[str] = Field(
        default_factory=list,
        description=(
            "Meaningful task objectives or subtasks that have "
            "already been completed."
        ),
    )

    unresolved_needs: list[str] = Field(
        default_factory=list,
        description=(
            "Information, actions, or decisions still required " "to complete the task."
        ),
    )


class ExecutionAttempt(BaseModel):
    """
    Compact record of one execution attempt performed while
    working on a Terminal Agent task.

    This model stores execution history required for planning,
    evaluation, loop detection, and debugging.

    It does not store complete raw tool results or task knowledge.
    """

    attempt_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description=("Unique identifier of this execution attempt."),
    )

    step: int = Field(
        ge=1,
        description=("Sequential execution step number within the task."),
    )

    capability: str = Field(
        min_length=1,
        description=("Name of the capability selected for this attempt."),
    )

    strategy: str = Field(
        min_length=1,
        description=(
            "Compact description of the approach chosen by the "
            "Planner for this attempt."
        ),
    )

    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description=("Arguments supplied to the selected capability."),
    )

    status: AttemptStatus = Field(
        default=AttemptStatus.PENDING,
        description=("Current lifecycle status of the execution attempt."),
    )

    outcome: ExecutionOutcome | str | None = Field(
        default=None,
        description=("Compact description of what happened during execution."),
    )

    progress_made: list[str] | bool | None = Field(
        default=None,
        description=(
            "Whether the attempt made meaningful progress toward " "the task goal."
        ),
    )

    error: str | None = Field(
        default=None,
        description=("Compact error information when execution fails."),
    )

    started_at: datetime = Field(
        default_factory=utc_now,
        description=("UTC timestamp when the attempt was created."),
    )

    completed_at: datetime | None = Field(
        default=None,
        description=("UTC timestamp when the attempt finished."),
    )

    artifact_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Identifiers of artifacts created during this " "execution attempt."
        ),
    )


class ExecutionMemory(BaseModel):
    """
    Task-scoped execution history maintained while the Terminal
    Agent works toward a goal.

    This model records execution attempts. It does not store
    current task knowledge or complete raw tool observations.
    """

    attempts: list[ExecutionAttempt] = Field(
        default_factory=list,
        description=("Ordered execution attempts performed during the task."),
    )


class ArtifactReference(BaseModel):
    """
    Lightweight reference to an artifact containing complete
    or large evidence produced during Terminal Agent execution.

    This model is safe to retain in graph state and memory because
    it does not contain the artifact's complete raw data.
    """

    artifact_id: str = Field(
        min_length=1,
        description="Unique identifier of the referenced artifact.",
    )

    artifact_type: str = Field(
        min_length=1,
        description=("Type of information stored by the artifact."),
    )

    summary: str = Field(
        default="",
        description=("Compact description of the artifact's contents."),
    )

    source: str = Field(
        min_length=1,
        description=("Capability or subsystem that produced the artifact."),
    )

    scope: MemoryScope = Field(
        default=MemoryScope.TASK,
        description=("Lifetime and visibility scope of the artifact."),
    )


class ThreadMemory(BaseModel):
    """
    Context retained across multiple Terminal Agent tasks
    belonging to the same conversation thread.

    Thread memory stores compact continuity information useful
    for future tasks. It does not store complete task state,
    execution history, raw tool results, or persistent knowledge.
    """

    known_context: list[str] = Field(
        default_factory=list,
        description=(
            "Relevant context learned during previous tasks in "
            "the current conversation thread."
        ),
    )

    relevant_resources: list[str] = Field(
        default_factory=list,
        description=(
            "Resources discovered during previous tasks that may "
            "be useful for future tasks in this thread."
        ),
    )

    previous_task_outcomes: list[str] = Field(
        default_factory=list,
        description=(
            "Compact outcomes of previously completed tasks in "
            "this conversation thread."
        ),
    )


class PersistentMemoryEntry(BaseModel):
    """
    One durable piece of knowledge retained across Terminal Agent
    tasks, threads, and sessions.

    Persistent memory entries represent stable, reusable knowledge.
    They do not store execution history or complete raw evidence.
    """

    memory_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description=("Unique identifier of the persistent memory entry."),
    )

    content: str = Field(
        min_length=1,
        description=("Stable reusable knowledge represented by this memory."),
    )

    namespace: str = Field(
        min_length=1,
        description=(
            "Logical namespace used to organize and retrieve " "persistent memories."
        ),
    )

    source: str = Field(
        min_length=1,
        description=(
            "Origin of the persistent memory, such as a task, "
            "subsystem, or memory promotion process."
        ),
    )

    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=("Confidence that the stored knowledge is accurate."),
    )

    status: MemoryStatus = Field(
        default=MemoryStatus.ACTIVE,
        description=("Current lifecycle status of the persistent memory."),
    )

    supersedes: str | None = Field(
        default=None,
        description=(
            "Identifier of an older persistent memory entry " "replaced by this entry."
        ),
    )

    created_at: datetime = Field(
        default_factory=utc_now,
        description=("UTC timestamp when the memory was created."),
    )

    updated_at: datetime = Field(
        default_factory=utc_now,
        description=("UTC timestamp of the latest memory update."),
    )


class PersistentMemory(BaseModel):
    """
    Relevant persistent knowledge loaded for the current
    Terminal Agent task.

    This model is a runtime view of durable memory entries.
    The persistent memory repository remains the authoritative
    storage system.
    """

    entries: list[PersistentMemoryEntry] = Field(
        default_factory=list,
        description=(
            "Persistent memory entries relevant to the " "current Terminal Agent task."
        ),
    )


class EphemeralExecutionState(BaseModel):
    """
    Temporary execution data used during the current Terminal Agent
    planning and execution cycle.

    Ephemeral execution state coordinates graph nodes. It does not
    represent task, thread, artifact, or persistent memory.
    """

    planning_output: PlanningOutput | None = Field(
        default=None,
        description=("Current planning decision produced by the Planner."),
    )

    raw_result: dict[str, Any] | str | None = Field(
        default=None,
        description=(
            "Unprocessed result produced by the current capability " "execution."
        ),
    )

    current_error: str | None = Field(
        default=None,
        description=("Error associated with the current execution cycle."),
    )

    evaluation: EvaluatorDecision | None = Field(
        default=None,
        description=(
            "Current evaluation decision produced after processing "
            "the execution result."
        ),
    )

    current_attempt_id: str | None = Field(
        default=None,
        description=(
            "Identifier of the execution attempt currently being " "processed."
        ),
    )


class TerminalTaskInput(BaseModel):
    """
    External input used to start a new Terminal Agent task.

    This model represents the public task invocation contract.
    Internal execution and memory state are initialized by the
    Terminal Agent.
    """

    goal: str = Field(
        min_length=1,
        description=("Goal the Terminal Agent should accomplish."),
    )


# FAKE MODEL

class FAKE_MODEL(BaseModel):
    """
    Single planning decision produced by the planner.
    """

    answer: str = Field(description="response from the model.")
    