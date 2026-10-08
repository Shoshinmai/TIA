from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any, Callable

from runtime.concurrent_debug import (
    ConcurrentDebugSession,
)

from runtime.task_execution import (
    TaskExecutionContext,
    TaskExecutionResult,
    TaskExecutionStatus,
)

from runtime.task_runner import (
    AsyncTaskRunner,
)

from runtime.task_runner_impl import (
    TaskRunner,
)

from task_executor.task_worker import (
    TaskWorker,
)

from task_plan.models import (
    TaskItem,
)


ConcurrentEventListener = Callable[[dict[str, Any]], None]
_concurrent_event_listener: ContextVar[ConcurrentEventListener | None] = ContextVar(
    "tia_concurrent_event_listener",
    default=None,
)
_cancel_check: ContextVar[Callable[[], bool] | None] = ContextVar(
    "tia_cancel_check",
    default=None,
)


def set_cancel_check(check: Callable[[], bool] | None):
    return _cancel_check.set(check)


def reset_cancel_check(token) -> None:
    _cancel_check.reset(token)


def set_concurrent_event_listener(
    listener: ConcurrentEventListener | None,
):
    return _concurrent_event_listener.set(listener)


def reset_concurrent_event_listener(token) -> None:
    _concurrent_event_listener.reset(token)


def _emit_concurrent_event(
    *,
    plan_id: str,
    task_id: str,
    event: str,
    **metadata: Any,
) -> None:
    listener = _concurrent_event_listener.get()
    if listener is not None:
        listener(
            {
                "plan_id": plan_id,
                "task_id": task_id,
                "event": event,
                **metadata,
            }
        )


class ConcurrentTaskExecutor:
    """
    Execute an explicitly supplied batch of independent tasks
    concurrently.

    Each task receives its own TaskWorker / TaskRunner /
    WorkflowRuntime stack.

    This is important because worker execution is task-local.
    Sharing one TaskWorker or WorkflowRuntime across concurrent
    tasks unnecessarily couples their runtime objects.

    This class does not:
    - discover READY tasks
    - mutate TaskPlan state
    - resolve dependencies
    - release dependent tasks
    - perform central result reconciliation

    It only executes the supplied execution wave and returns
    one TaskExecutionResult per task.
    """

    def __init__(
        self,
        *,
        runner: AsyncTaskRunner,
        max_concurrency: int = 3,
    ) -> None:

        if max_concurrency < 1:
            raise ValueError(
                "max_concurrency must be at least 1."
            )

        self.runner = runner
        self.max_concurrency = max_concurrency

    async def execute(
        self,
        *,
        plan_id: str,
        tasks: list[TaskItem],
        state: dict,
    ) -> list[TaskExecutionResult]:

        if not tasks:
            return []

        semaphore = asyncio.Semaphore(
            self.max_concurrency
        )

        # ======================================================
        # TEMPORARY CONCURRENT DEBUGGING
        # ======================================================

        debug_session = ConcurrentDebugSession(
            plan_id=plan_id,
            tasks=tasks,
        )

        # Worker execution stays inside the service process. The debug
        # session records lifecycle events but never opens terminal tabs.

        for task in tasks:

            debug_session.write(
                task_id=task.task_id,
                event="WAVE_START",
                message=(
                    "Concurrent wave started with "
                    f"{len(tasks)} task(s)."
                ),
                plan_id=plan_id,
                task_count=len(tasks),
            )
            _emit_concurrent_event(
                plan_id=plan_id,
                task_id=task.task_id,
                event="wave_started",
                task_count=len(tasks),
                objective=task.objective,
            )

        async def execute_one(
            task: TaskItem,
        ) -> TaskExecutionResult:

            async with semaphore:

                context = TaskExecutionContext(
                    plan_id=plan_id,
                    task_id=task.task_id,
                    status=TaskExecutionStatus.CREATED,
                    metadata={
                        "task_objective": task.objective,
                    },
                )

                # ==================================================
                # IMPORTANT:
                #
                # Every concurrent task gets its OWN execution
                # stack.
                #
                # Before this change:
                #
                #     one TaskWorker
                #          ↓
                #     one TaskRunner
                #          ↓
                #     one WorkflowRuntime
                #
                # was shared by every worker.
                #
                # Now:
                #
                #     Task A → Worker A → Runner A → Runtime A
                #     Task B → Worker B → Runner B → Runtime B
                #     Task C → Worker C → Runner C → Runtime C
                #
                # The debug session remains shared intentionally
                # because it is only a logging coordinator.
                # ==================================================

                worker = TaskWorker(
                    debug_session=debug_session,
                    event_listener=lambda event, metadata: _emit_concurrent_event(
                        plan_id=plan_id,
                        task_id=task.task_id,
                        event=event,
                        **metadata,
                    ),
                    cancel_check=_cancel_check.get(),
                )

                runner = TaskRunner(
                    worker=worker,
                    debug_session=debug_session,
                    event_listener=worker.event_listener,
                    cancel_check=worker.cancel_check,
                )

                debug_session.write(
                    task_id=task.task_id,
                    event="START",
                    message=(
                        "Worker entered concurrent execution."
                    ),
                    objective=task.objective,
                )
                _emit_concurrent_event(
                    plan_id=plan_id,
                    task_id=task.task_id,
                    event="worker_started",
                    objective=task.objective,
                )

                try:

                    context.status = (
                        TaskExecutionStatus.RUNNING
                    )

                    debug_session.write(
                        task_id=task.task_id,
                        event="RUNNING",
                        message=(
                            "TaskRunner execution started."
                        ),
                    )
                    _emit_concurrent_event(
                        plan_id=plan_id,
                        task_id=task.task_id,
                        event="worker_running",
                    )

                    # --------------------------------------------------
                    # Explicit marker immediately before the LLM call
                    # is reached inside TaskWorker.
                    # --------------------------------------------------

                    debug_session.write(
                        task_id=task.task_id,
                        event="WORKER_DISPATCH",
                        message=(
                            "Dispatching isolated worker "
                            "execution stack."
                        ),
                    )
                    _emit_concurrent_event(
                        plan_id=plan_id,
                        task_id=task.task_id,
                        event="worker_dispatched",
                    )

                    result = await runner.execute_task(
                        context,
                        task=task,
                        state=state,
                    )

                    debug_session.write(
                        task_id=task.task_id,
                        event="RESULT",
                        message=(
                            "TaskRunner returned a result."
                        ),
                        status=result.status.value,
                        execution_id=result.execution_id,
                        workflow_id=result.workflow_id,
                        processing_results=len(
                            result.processing_results
                        ),
                    )
                    _emit_concurrent_event(
                        plan_id=plan_id,
                        task_id=task.task_id,
                        event="worker_result",
                        status=result.status.value,
                        workflow_id=result.workflow_id,
                        workflow=(
                            result.workflow.model_dump(mode="json")
                            if result.workflow is not None
                            else None
                        ),
                        error=result.error,
                    )

                    debug_session.close_worker(
                        task_id=task.task_id,
                        status=result.status.value,
                    )
                    _emit_concurrent_event(
                        plan_id=plan_id,
                        task_id=task.task_id,
                        event="worker_finished",
                        status=result.status.value,
                        error=result.error,
                    )

                    return result

                except asyncio.CancelledError:

                    context.status = (
                        TaskExecutionStatus.CANCELLED
                    )

                    context.error = (
                        "Task execution was cancelled."
                    )

                    debug_session.write(
                        task_id=task.task_id,
                        event="CANCELLED",
                        message=(
                            "Worker task was cancelled."
                        ),
                    )
                    _emit_concurrent_event(
                        plan_id=plan_id,
                        task_id=task.task_id,
                        event="worker_cancelled",
                        error=context.error,
                    )

                    debug_session.close_worker(
                        task_id=task.task_id,
                        status="cancelled",
                        error=context.error,
                    )

                    raise

                except Exception as error:

                    context.status = (
                        TaskExecutionStatus.FAILED
                    )

                    context.error = str(error)

                    debug_session.write(
                        task_id=task.task_id,
                        event="ERROR",
                        message=(
                            "TaskRunner raised an exception."
                        ),
                        error=str(error),
                    )
                    _emit_concurrent_event(
                        plan_id=plan_id,
                        task_id=task.task_id,
                        event="worker_failed",
                        error=str(error),
                    )

                    result = TaskExecutionResult(
                        execution_id=context.execution_id,
                        plan_id=context.plan_id,
                        task_id=context.task_id,
                        status=(
                            TaskExecutionStatus.FAILED
                        ),
                        workflow_id=(
                            context.workflow.workflow_id
                            if context.workflow is not None
                            else None
                        ),
                        result=context.result,
                        error=str(error),
                        metadata=context.metadata,
                        processing_results=[],
                    )

                    debug_session.close_worker(
                        task_id=task.task_id,
                        status="failed",
                        error=str(error),
                    )

                    return result

        # ======================================================
        # REAL CONCURRENT EXECUTION
        # ======================================================
        #
        # All execute_one() coroutines are scheduled together.
        #
        # The semaphore limits the number of active workers but
        # does NOT serialize them.
        # ======================================================

        print()
        print(
            "[CONCURRENT EXECUTOR] "
            f"Dispatching {len(tasks)} task(s) "
            f"with max_concurrency="
            f"{self.max_concurrency}"
        )

        print(
            "[CONCURRENT EXECUTOR] "
            "Tasks="
            f"{[task.task_id for task in tasks]}"
        )

        raw_results = await asyncio.gather(
            *(execute_one(task) for task in tasks),
            return_exceptions=True,
        )

        results: list[TaskExecutionResult] = []

        for task, raw_result in zip(
            tasks,
            raw_results,
        ):

            if isinstance(
                raw_result,
                TaskExecutionResult,
            ):

                results.append(
                    raw_result
                )

                continue

            if isinstance(
                raw_result,
                asyncio.CancelledError,
            ):

                results.append(
                    TaskExecutionResult(
                        execution_id="",
                        plan_id=plan_id,
                        task_id=task.task_id,
                        status=(
                            TaskExecutionStatus.CANCELLED
                        ),
                        error=(
                            "Task execution was cancelled."
                        ),
                        processing_results=[],
                    )
                )

                continue

            if isinstance(
                raw_result,
                Exception,
            ):

                results.append(
                    TaskExecutionResult(
                        execution_id="",
                        plan_id=plan_id,
                        task_id=task.task_id,
                        status=(
                            TaskExecutionStatus.FAILED
                        ),
                        error=str(raw_result),
                        processing_results=[],
                    )
                )

                continue

            raise TypeError(
                "Concurrent task executor received an "
                "unexpected result type: "
                f"{type(raw_result)!r}"
            )

        # ======================================================
        # TEMPORARY DEBUGGING: WAVE RESULT COLLECTION
        # ======================================================

        for result in results:

            debug_session.write(
                task_id=result.task_id,
                event="RECONCILED",
                message=(
                    "Task result collected by "
                    "ConcurrentTaskExecutor."
                ),
                status=result.status.value,
                processing_results=len(
                    result.processing_results
                ),
            )
            _emit_concurrent_event(
                plan_id=plan_id,
                task_id=result.task_id,
                event="worker_reconciled",
                status=result.status.value,
            )

        print()
        print(
            "[CONCURRENT EXECUTOR] "
            "All workers returned."
        )

        print(
            "[CONCURRENT EXECUTOR] "
            f"Results="
            f"{[(r.task_id, r.status.value) for r in results]}"
        )

        return results