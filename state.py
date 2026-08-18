from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from agents.terminal.critics.integration import CriticRuntimeEvent
from agents.terminal.models import (
    ActiveTaskMemory,
    ArtifactReference,
    EphemeralExecutionState,
    ExecutionMemory,
    ObservationInput,
    PersistentMemory,
    PlanningOutput,
    TaskContext,
    ThreadMemory,
)
from agents.terminal.result_processing.models import RuntimeProcessingResult
from agents.terminal.runtime.models import RuntimeState
from agents.terminal.task_executor.models import ExecutionWorkflow
from agents.terminal.task_plan.models import TaskPlan


class TerminalState(TypedDict):

    # ==========================================================
    # NEW STRUCTURED STATE
    # ==========================================================

    task: TaskContext

    active_memory: ActiveTaskMemory | None

    execution_memory: ExecutionMemory

    artifact_references: list[ArtifactReference]

    thread_memory: ThreadMemory

    persistent_memory: PersistentMemory

    ephemeral_execution_state: EphemeralExecutionState
    
    runtime_state: RuntimeState
    
    task_plan: TaskPlan | None
    
    execution_workflow: ExecutionWorkflow | None
    
    critic_runtime_event: CriticRuntimeEvent | None

    # ==========================================================
    # GRAPH / TOOL PROTOCOL
    # ==========================================================

    messages: Annotated[list[AnyMessage], add_messages]


    # ==========================================================
    # LEGACY EXECUTION FIELDS
    #
    # Temporarily retained while graph nodes are migrated to the
    # new structured state architecture.
    # ==========================================================

    goal: str

    action_type: str

    thought: str

    command: str

    tool_name: str

    tool_input: str

    success: bool

    error: str

    done: bool

    step_count: int

    valid_command: bool

    validation_error: str

    safety_passed: bool

    safety_reason: str

    raw_observation: str

    observation_input: ObservationInput | None
    
    runtime_processing_result: RuntimeProcessingResult | None

    artifact_ids: list[str]

    artifact_type: Literal[
        "file_listing",
        "package_list",
        "log",
        "git_diff",
        "command_output",
    ]

    planner_output: Optional[PlanningOutput]