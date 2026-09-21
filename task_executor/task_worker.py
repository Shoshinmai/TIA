from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Callable

from memory.execution_manager import (
    ExecutionMemoryManager,
)

from prompts.executor_prompt import (
    TERMINAL_EXECUTOR_PROMPT,
)

from result_processing.processor import (
    process_tool_result,
)

from runtime.concurrent_debug import (
    ConcurrentDebugSession,
)

from runtime.task_execution import (
    TaskExecutionContext,
    TaskExecutionResult,
    TaskExecutionStatus,
)

from task_executor.context_builder import (
    build_execution_context_for_task,
)

from task_executor.models import (
    ExecutionWorkflow,
    ExecutorOutput,
)

from task_executor.workflow_runtime import (
    WorkflowRuntime,
)

from task_plan.models import (
    TaskItem,
)

from llm.llmclient import call_nvidia


def _tool_output(tool_result: Any) -> str:
    """Extract a bounded preview of the actual tool output payload."""

    if not isinstance(tool_result, dict):
        return ""
    for key in ("output", "content", "summary", "stdout"):
        value = tool_result.get(key)
        if value:
            return str(value)[:2000]
    return ""


class TaskWorker:
    """
    Task-local execution worker.

    A TaskWorker executes one explicitly assigned TaskItem.

    The worker owns:
    - task-specific execution context
    - workflow generation
    - workflow execution
    - task-local result processing
    - task-local ExecutionMemory lifecycle
    - task-local RuntimeProcessingResult collection

    The worker does NOT:
    - select tasks
    - mutate the central TaskPlan
    - update task dependencies
    - release newly ready tasks
    - schedule other workers
    - mutate central runtime memory
    """

    def __init__(
        self,
        *,
        workflow_runtime: WorkflowRuntime | None = None,
        debug_session: ConcurrentDebugSession | None = None,
        event_listener: Callable[[str, dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:

        self.workflow_runtime = (
            workflow_runtime
            if workflow_runtime is not None
            else WorkflowRuntime(
                step_listener=(
                    (lambda payload: self._emit("workflow_step_started", **payload))
                    if event_listener is not None
                    else None
                ),
            )
        )

        self.debug_session = debug_session
        self.event_listener = event_listener
        self.cancel_check = cancel_check

    def _emit(self, event: str, **metadata: Any) -> None:
        if self.event_listener is not None:
            self.event_listener(event, metadata)

    def _raise_if_cancelled(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise asyncio.CancelledError()

    # ==========================================================
    # Temporary concurrent debugging
    # ==========================================================

    def _debug(
        self,
        *,
        task_id: str,
        event: str,
        message: str,
        **metadata,
    ) -> None:

        if self.debug_session is None:
            return

        self.debug_session.write(
            task_id=task_id,
            event=event,
            message=message,
            **metadata,
        )

    async def execute(
        self,
        *,
        state: dict[str, Any],
        task_execution: TaskExecutionContext,
        task: TaskItem,
    ) -> TaskExecutionResult:
        """
        Execute one explicitly assigned task.

        The task receives one task-local ExecutionMemory attempt.
        Every workflow step is processed through the Runtime
        Processing Pipeline.

        The worker does not mutate central runtime state.
        """

        workflow: ExecutionWorkflow | None = None

        tool_results: list[Any] = []

        processing_results = []

        attempt_id: str | None = None

        # This is deliberately kept separate from the original
        # live attempt object. It will contain a detached,
        # finalized record for TaskExecutionResult.
        finalized_attempt = None

        try:
            self._raise_if_cancelled()

            # ==================================================
            # 1. Mark local execution as running
            # ==================================================

            task_execution.status = TaskExecutionStatus.RUNNING

            self._debug(
                task_id=task.task_id,
                event="WORKER",
                message="TaskWorker started execution.",
                objective=task.objective,
            )

            # ==================================================
            # 2. Build task-local Executor context
            # ==================================================

            execution_context = build_execution_context_for_task(
                state=state,
                task=task,
            )

            prompt = TERMINAL_EXECUTOR_PROMPT.format(
                **execution_context.model_dump()
            )

            self._debug(
                task_id=task.task_id,
                event="CONTEXT",
                message="Task-local Executor context built.",
            )

            # ==================================================
            # 3. Generate task-local workflow
            # ==================================================

            self._debug(
                task_id=task.task_id,
                event="LLM",
                message="Requesting task-local workflow from Executor.",
            )

            executor_output = await call_nvidia(
                prompt,
                "openai/gpt-oss-20b",
                # "mistralai/mistral-nemotron",
                # "poolside/laguna-xs-2.1",
                # "nvidia/nemotron-3-super-120b-a12b",
                subagent=True,
                state_model=ExecutorOutput,
            )

            workflow = executor_output.workflow

            # ==================================================
            # 4. Bind workflow to assigned task
            # ==================================================

            workflow.task_id = task.task_id
            workflow.objective = task.objective

            task_execution.workflow = workflow
            self._emit(
                "workflow_created",
                workflow=workflow.model_dump(mode="json"),
            )

            print("\n========== TASK WORKER ==========")
            print(f"TASK ID: {task.task_id}")
            print(f"OBJECTIVE: {task.objective}")

            print("\n========== WORKFLOW ==========")
            print(workflow.model_dump())

            for index, step in enumerate(
                workflow.steps,
                start=1,
            ):
                print(
                    f"\n[STEP-{index}] --> "
                    f"{step.description} : "
                    f"(TOOL -> {step.capability} | "
                    f"ARGS -> {step.arguments} | "
                    f"STATUS -> {step.status})"
                )

            self._debug(
                task_id=task.task_id,
                event="WORKFLOW",
                message="Executor workflow generated.",
                workflow_id=workflow.workflow_id,
                step_count=len(workflow.steps),
            )

            for index, step in enumerate(
                workflow.steps,
                start=1,
            ):
                self._debug(
                    task_id=task.task_id,
                    event="WORKFLOW_STEP",
                    message=f"Workflow step {index}.",
                    step_id=step.step_id,
                    description=step.description,
                    capability=step.capability,
                    arguments=step.arguments,
                    status=step.status.value,
                )

            # ==================================================
            # 5. Start task execution-memory attempt
            # ==================================================

            first_step = workflow.steps[0]

            attempt = ExecutionMemoryManager.start_attempt(
                execution_memory=state["execution_memory"],
                capability=first_step.capability,
                strategy=workflow.execution_strategy,
                arguments=first_step.arguments,
            )

            attempt_id = attempt.attempt_id

            task_execution.active_attempt_id = attempt_id

            self._debug(
                task_id=task.task_id,
                event="ATTEMPT",
                message="ExecutionMemory attempt started.",
                attempt_id=attempt_id,
                capability=first_step.capability,
            )

            print("\n========== EXECUTION MEMORY ==========")
            print(f"TASK ID: {task.task_id}")
            print(f"ATTEMPT ID: {attempt_id}")
            print("STATUS: running")

            # ==================================================
            # 6. Execute workflow until terminal
            # ==================================================

            while workflow.status.value not in (
                "completed",
                "failed",
                "cancelled",
            ):

                self._raise_if_cancelled()

                current_step = next(
                    (
                        step
                        for step in workflow.steps
                        if step.status.value
                        in (
                            "pending",
                            "in_progress",
                        )
                    ),
                    None,
                )

                self._debug(
                    task_id=task.task_id,
                    event="STEP_START",
                    message="Executing workflow step.",
                    step_id=(
                        current_step.step_id
                        if current_step is not None
                        else None
                    ),
                    capability=(
                        current_step.capability
                        if current_step is not None
                        else None
                    ),
                )

                execution_result = (
                    self._emit(
                        "tool_started",
                        step_id=current_step.step_id if current_step is not None else None,
                        capability=current_step.capability if current_step is not None else None,
                        command=current_step.arguments.get("command", "") if current_step is not None else "",
                        description=current_step.description if current_step is not None else "",
                    ),
                    await self.workflow_runtime.execute_next_step(
                        workflow,
                    ),
                )[1]

                workflow = execution_result["workflow"]

                task_execution.workflow = workflow

                tool_result = execution_result.get(
                    "tool_result"
                )

                step_id = execution_result.get(
                    "step_id"
                )

                capability = execution_result.get(
                    "capability"
                )

                self._debug(
                    task_id=task.task_id,
                    event="STEP_RESULT",
                    message="WorkflowRuntime completed the current step.",
                    step_id=step_id,
                    capability=capability,
                    completed=execution_result.get(
                        "completed"
                    ),
                    workflow_status=workflow.status.value,
                )
                tool_step = (
                    next(
                        (
                            step
                            for step in workflow.steps
                            if step.step_id == step_id
                        ),
                        None,
                    )
                    if step_id
                    else None
                )
                self._emit(
                    "tool_finished",
                    step_id=step_id,
                    capability=capability,
                    command=(
                        tool_step.arguments.get("command", "")
                        if tool_step is not None
                        else ""
                    ),
                    success=tool_result.get("success", True) if isinstance(tool_result, dict) else False,
                    error=tool_result.get("error", "") if isinstance(tool_result, dict) else "",
                    output=_tool_output(tool_result),
                )

                # --------------------------------------------------
                # Process actual tool result
                # --------------------------------------------------

                if tool_result is not None:

                    tool_results.append(
                        tool_result
                    )

                    if not capability:
                        raise ValueError(
                            "WorkflowRuntime returned a tool "
                            "result without the executing "
                            "capability."
                        )

                    processed_result = (
                        await process_tool_result(
                            state=state,
                            tool_name=capability,
                            raw_result=tool_result,
                            attempt=(
                                len(processing_results) + 1
                            ),
                        )
                    )

                    artifact_action = (
                        processed_result
                        .artifact_decision
                        .action
                        .value
                    )

                    self._debug(
                        task_id=task.task_id,
                        event="PROCESSING",
                        message=(
                            "Tool result passed through "
                            "the Runtime Processing Pipeline."
                        ),
                        step_id=step_id,
                        capability=capability,
                        artifact_action=artifact_action,
                    )

                    processing_results.append(
                        processed_result
                    )

                    print(
                        "\n========== TASK RESULT PROCESSED =========="
                    )

                    print(
                        f"TASK ID: {task.task_id}"
                    )

                    print(
                        f"STEP ID: {step_id}"
                    )

                    print(
                        f"CAPABILITY: {capability}"
                    )

                    print(
                        processed_result
                    )

                if execution_result.get("completed"):
                    break

            # ==================================================
            # 7. Finalize ExecutionMemory attempt FIRST
            # ==================================================

            if attempt_id is not None:

                final_processing_result = (
                    processing_results[-1]
                    if processing_results
                    else None
                )

                final_execution = (
                    final_processing_result
                    .normalized_result
                    .execution
                    if final_processing_result is not None
                    else None
                )

                execution_success = (
                    workflow.status.value == "completed"
                    and (
                        final_execution.success
                        if final_execution is not None
                        else False
                    )
                )

                execution_error = (
                    final_execution.stderr
                    if final_execution is not None
                    else (
                        "Workflow terminated before a "
                        "RuntimeProcessingResult was produced."
                    )
                )

                print(
                    "\n[ATTEMPT FINALIZE] "
                    f"task={task.task_id} "
                    f"attempt={attempt_id} "
                    f"success={execution_success}"
                )

                ExecutionMemoryManager.finish_attempt(
                    execution_memory=state["execution_memory"],
                    attempt_id=attempt_id,
                    runtime_result=final_processing_result,
                    success=execution_success,
                    error=execution_error,
                )

                # --------------------------------------------------
                # IMPORTANT:
                #
                # Re-resolve the attempt AFTER finalization and
                # detach it from the worker-local ExecutionMemory.
                # --------------------------------------------------

                finalized_attempt = next(
                    (
                        worker_attempt
                        for worker_attempt
                        in state["execution_memory"].attempts
                        if worker_attempt.attempt_id
                        == attempt_id
                    ),
                    None,
                )

                if finalized_attempt is None:
                    raise RuntimeError(
                        "Execution attempt disappeared after "
                        "finalization: "
                        f"{attempt_id}"
                    )

                if finalized_attempt.status.value not in (
                    "succeeded",
                    "failed",
                ):
                    raise RuntimeError(
                        "Execution attempt remained non-terminal "
                        "after finish_attempt(): "
                        f"{attempt_id} "
                        f"status={finalized_attempt.status.value}"
                    )

                # Detach the terminal record from the mutable
                # worker-local memory before returning it.
                finalized_attempt = deepcopy(
                    finalized_attempt
                )

                print(
                    "[ATTEMPT FINALIZE] "
                    f"Final status="
                    f"{finalized_attempt.status.value}"
                )

                self._debug(
                    task_id=task.task_id,
                    event="ATTEMPT_DONE",
                    message="ExecutionMemory attempt finalized.",
                    attempt_id=attempt_id,
                    status=finalized_attempt.status.value,
                    processing_results=len(
                        processing_results
                    ),
                )

                print(
                    "\n========== EXECUTION MEMORY =========="
                )

                print(
                    f"TASK ID: {task.task_id}"
                )

                print(
                    f"ATTEMPT ID: {attempt_id}"
                )

                print(
                    "PROCESSING RESULTS: "
                    f"{len(processing_results)}"
                )

                print("STATUS: finalized")

                print(
                    "FINAL ATTEMPT STATUS: "
                    f"{finalized_attempt.status.value}"
                )

            task_execution.active_attempt_id = None

            # ==================================================
            # 8. Build task-local result payload
            # ==================================================

            task_execution.result = {
                "tool_results": tool_results,
                "processing_results": [
                    result.model_dump()
                    for result in processing_results
                ],
            }

            self._debug(
                task_id=task.task_id,
                event="WORKFLOW_DONE",
                message="Task workflow reached terminal state.",
                workflow_id=workflow.workflow_id,
                workflow_status=workflow.status.value,
                processing_results=len(processing_results),
            )

            # ==================================================
            # 9. Mark local task execution terminal
            # ==================================================

            task_execution.status = (
                TaskExecutionStatus.COMPLETED
                if workflow.status.value == "completed"
                else TaskExecutionStatus.FAILED
            )

            self._debug(
                task_id=task.task_id,
                event="WORKER_DONE",
                message="TaskWorker completed execution.",
                status=task_execution.status.value,
                processing_results=len(processing_results),
            )

            return TaskExecutionResult(
                execution_id=task_execution.execution_id,
                execution_attempt_id=attempt_id,
                execution_attempt=finalized_attempt,
                plan_id=task_execution.plan_id,
                task_id=task_execution.task_id,
                status=task_execution.status,
                workflow_id=workflow.workflow_id,
                workflow=workflow,
                result=task_execution.result,
                error=task_execution.error,
                metadata=task_execution.metadata,
                processing_results=processing_results,
            )

        except asyncio.CancelledError:

            task_execution.status = (
                TaskExecutionStatus.CANCELLED
            )

            # --------------------------------------------------
            # Cancelled tasks still need their running attempt
            # finalized before the worker exits.
            # --------------------------------------------------

            if attempt_id is not None:

                try:

                    ExecutionMemoryManager.finish_attempt(
                        execution_memory=state[
                            "execution_memory"
                        ],
                        attempt_id=attempt_id,
                        runtime_result=None,
                        success=False,
                        error=(
                            "Task execution was cancelled."
                        ),
                    )

                    cancelled_attempt = next(
                        (
                            worker_attempt
                            for worker_attempt
                            in state[
                                "execution_memory"
                            ].attempts
                            if worker_attempt.attempt_id
                            == attempt_id
                        ),
                        None,
                    )

                    if cancelled_attempt is not None:
                        finalized_attempt = deepcopy(
                            cancelled_attempt
                        )

                except ValueError:
                    pass

            task_execution.active_attempt_id = None

            self._debug(
                task_id=task.task_id,
                event="CANCELLED",
                message="TaskWorker execution was cancelled.",
                attempt_id=attempt_id,
            )

            raise

        except Exception as error:

            task_execution.status = (
                TaskExecutionStatus.FAILED
            )

            task_execution.error = str(error)

            # --------------------------------------------------
            # A worker exception after start_attempt() must not
            # leave a RUNNING attempt behind.
            # --------------------------------------------------

            if attempt_id is not None:

                try:

                    ExecutionMemoryManager.finish_attempt(
                        execution_memory=state[
                            "execution_memory"
                        ],
                        attempt_id=attempt_id,
                        runtime_result=(
                            processing_results[-1]
                            if processing_results
                            else None
                        ),
                        success=False,
                        error=str(error),
                    )

                    failed_attempt = next(
                        (
                            worker_attempt
                            for worker_attempt
                            in state[
                                "execution_memory"
                            ].attempts
                            if worker_attempt.attempt_id
                            == attempt_id
                        ),
                        None,
                    )

                    if failed_attempt is not None:

                        if failed_attempt.status.value not in (
                            "succeeded",
                            "failed",
                        ):
                            raise RuntimeError(
                                "Execution attempt remained "
                                "non-terminal after failure "
                                "finalization: "
                                f"{attempt_id}"
                            )

                        finalized_attempt = deepcopy(
                            failed_attempt
                        )

                except ValueError:
                    # Preserve the original worker exception.
                    pass

            task_execution.active_attempt_id = None

            self._debug(
                task_id=task.task_id,
                event="ERROR",
                message="TaskWorker execution failed.",
                attempt_id=attempt_id,
                error=str(error),
            )

            return TaskExecutionResult(
                execution_id=task_execution.execution_id,
                execution_attempt_id=attempt_id,
                execution_attempt=finalized_attempt,
                plan_id=task_execution.plan_id,
                task_id=task_execution.task_id,
                status=TaskExecutionStatus.FAILED,
                workflow_id=(
                    workflow.workflow_id
                    if workflow is not None
                    else None
                ),
                workflow=workflow,
                result=task_execution.result,
                error=str(error),
                metadata=task_execution.metadata,
                processing_results=processing_results,
            )