from __future__ import annotations

from typing import Any, Callable
from runtime.concurrent_debug import (
    ConcurrentDebugSession,
)
from runtime.task_execution import (
    TaskExecutionContext,
    TaskExecutionResult,
)
from runtime.task_runner import (
    AsyncTaskRunner,
)
from runtime.task_state_snapshot import (
    build_task_execution_snapshot,
)
from task_executor.task_worker import (
    TaskWorker,
)
from task_plan.models import TaskItem


class TaskRunner(AsyncTaskRunner):
    """
    Concrete adapter between AsyncTaskRunner and TaskWorker.

    The runner constructs the isolated state snapshot for the
    assigned task and delegates execution to TaskWorker.

    The optional ConcurrentDebugSession is only for temporary
    debugging. It does not participate in execution semantics.
    """

    def __init__(
        self,
        *,
        worker: TaskWorker | None = None,
        debug_session: ConcurrentDebugSession | None = None,
        event_listener: Callable[[str, dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:

        self.debug_session = debug_session
        self.event_listener = event_listener
        self.cancel_check = cancel_check

        self.worker = (
            worker
            if worker is not None
            else TaskWorker(
                debug_session=debug_session,
                event_listener=event_listener,
                cancel_check=cancel_check,
            )
        )

        # If an externally supplied worker was provided, make
        # sure the debugging session is propagated to it as well.
        if debug_session is not None:
            self.worker.debug_session = debug_session
        if event_listener is not None:
            self.worker.event_listener = event_listener
        if cancel_check is not None:
            self.worker.cancel_check = cancel_check

    async def execute_task(
        self,
        context: TaskExecutionContext,
        *,
        task: TaskItem,
        state: dict,
    ) -> TaskExecutionResult:

        task_state = build_task_execution_snapshot(
            state=state,
            task=task,
        )

        return await self.worker.execute(
            state=task_state,
            task_execution=context,
            task=task,
        )