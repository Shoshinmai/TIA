from agents.terminal.state import TerminalState
from agents.terminal.task_executor.models import ExecutorOutput
from agents.terminal.task_executor.context_builder import (
    build_execution_context,
)
from agents.terminal.prompts.executor_prompt import (
    TERMINAL_EXECUTOR_PROMPT,
)
from agents.terminal.task_plan.manager import TaskPlanManager
from llm.llmclient import call_nvidia, call_ollama


def _start_current_task(
    state,
) -> None:
    """
    Mark the TaskPlan task associated with the generated execution
    workflow as IN_PROGRESS.

    This mutation happens only after the Task Executor has
    successfully produced a workflow.

    If a task is already IN_PROGRESS, execution is being resumed
    or retried, so no new start transition is required.
    """

    task_plan = state.get("task_plan")

    if task_plan is None:
        raise ValueError(
            "Cannot start execution without a TaskPlan."
        )

    # ----------------------------------------------------------
    # Existing active task
    # ----------------------------------------------------------

    existing_task = TaskPlanManager.get_in_progress_task(
        plan=task_plan,
    )

    if existing_task is not None:
        return existing_task

    # ----------------------------------------------------------
    # Select the next executable task
    # ----------------------------------------------------------

    current_task = TaskPlanManager.get_current_task(
        task_plan,
    )

    if current_task is None:
        raise ValueError(
            "Cannot start execution because the TaskPlan has "
            "no executable task."
        )

    # ----------------------------------------------------------
    # Commit the TaskPlan task to execution
    # ----------------------------------------------------------

    TaskPlanManager.start_task(
        plan=task_plan,
        task_id=current_task.task_id,
    )
    return current_task


def terminal_task_executor_node(state: TerminalState):
    """
    Generate an execution workflow for the current objective.

    The Executor is responsible only for tactical workflow design.
    It does not execute capabilities.

    Once a valid workflow has been generated, the associated
    TaskPlan task is moved to IN_PROGRESS so that the task lifecycle
    reflects the execution boundary.
    """

    execution_context = build_execution_context(
        state=state,
    )

    # print("\n========== EXECUTION CONTEXT ==========")
    # print(
    #     execution_context.model_dump()
    # )

    prompt = TERMINAL_EXECUTOR_PROMPT.format(
        **execution_context.model_dump()
    )

    # executor_output = call_ollama(
    #     prompt=prompt,
    #     model="qwen2.5-coder:7b",
    #     subagent=True,
    #     state_model=ExecutorOutput,
    # )

    executor_output = call_nvidia(
        prompt,
        # "openai/gpt-oss-20b",
        "nvidia/nemotron-3-ultra-550b-a55b",
        subagent=True,
        state_model=ExecutorOutput,
    )

    # ----------------------------------------------------------
    # The workflow has now been successfully generated.
    #
    # Only now do we transition the TaskPlan task into
    # IN_PROGRESS.
    # ----------------------------------------------------------

    current_task = _start_current_task(
        state,
    )

    # ----------------------------------------------------------
    # The TaskPlan owns the authoritative objective.
    #
    # The LLM only designs the tactical workflow. It must not
    # redefine which TaskItem the workflow belongs to.
    # ----------------------------------------------------------

    executor_output.workflow.objective = (
        current_task.objective
    )

    runtime_state = state.get(
        "runtime_state"
    )

    if runtime_state is not None:
        runtime_state.decision_context = None

    print("\n========== EXECUTOR ==========")
    print(
        executor_output.model_dump()
    )

    return {
        "execution_workflow": executor_output.workflow,
    }