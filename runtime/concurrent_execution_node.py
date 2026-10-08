from __future__ import annotations

from runtime.concurrent_task_executor import (
    ConcurrentTaskExecutor,
)
from runtime.events import RuntimeEvent
from runtime.plan_execution_outcome import (
    build_plan_execution_outcome,
)
from runtime.kernel import RuntimeKernel
from runtime.task_execution_coordinator import (
    TaskExecutionCoordinator,
)
from runtime.task_runner_impl import (
    TaskRunner,
)
from state import TerminalState
from task_executor.task_worker import (
    TaskWorker,
)
from task_plan.manager import TaskPlanManager


async def concurrent_execution_node(
    state: TerminalState,
) -> dict:
    """
    Execute exactly one concurrent execution wave.

    This node is the graph boundary between:

        concurrent worker execution
                ↓
        wave reconciliation
                ↓
              Critic

    The coordinator intentionally executes only the current READY
    wave. Newly-ready dependent tasks are returned to the Runtime
    rather than being automatically executed in this invocation.

    Workers operate on isolated task-local snapshots.

    The coordinator/reconciler owns the authoritative state
    transition after the complete wave.

    IMPORTANT:

    Completion of a concurrent wave does NOT automatically mean
    that the user's overall goal has been completed.

    When reconciliation exhausts the current TaskPlan, the runtime
    emits PLAN_EXHAUSTED rather than EXECUTION_COMPLETED. This
    preserves the semantic lifecycle used by the legacy runtime:

        PLAN_EXHAUSTED
              ↓
           REVIEWING
              ↓
            Critic
              ↓
       GOAL_COMPLETED /
       REPLAN_REQUIRED
    """

    task_plan = state.get(
        "task_plan",
    )

    if task_plan is None:
        raise ValueError(
            "Cannot start concurrent execution without "
            "a TaskPlan."
        )

    runtime_state = state.get(
        "runtime_state",
    )

    if runtime_state is None:
        raise ValueError(
            "Cannot start concurrent execution without "
            "RuntimeState."
        )

    # ==========================================================
    # TEMPORARY DEBUGGING
    # ==========================================================

    print()
    print("=" * 72)
    print("              CONCURRENT WAVE START")
    print("=" * 72)

    print(
        f"Plan: {task_plan.plan_id}"
    )

    print(
        f"Goal: {task_plan.goal}"
    )

    ready_tasks = [
        task
        for task in task_plan.tasks
        if task.status.value == "ready"
    ]

    print()
    print(
        "READY tasks admitted for this wave: "
        f"{len(ready_tasks)}"
    )

    print(
        "READY task IDs: "
        f"{[task.task_id for task in ready_tasks]}"
    )

    print(
        "Max concurrency: 3"
    )

    print()
    print("=" * 72)
    print("              EXECUTING CURRENT WAVE")
    print("=" * 72)

    # ==========================================================
    # Build concurrent execution stack
    # ==========================================================
    #
    # ConcurrentTaskExecutor creates an isolated Worker/Runner
    # execution stack for every task in the wave.
    # ==========================================================

    executor = ConcurrentTaskExecutor(
        runner=TaskRunner(
            worker=TaskWorker(),
        ),
        max_concurrency=3,
    )

    coordinator = TaskExecutionCoordinator(
        executor=executor,
    )

    # ==========================================================
    # Execute ONE dependency-aware wave
    # ==========================================================

    coordinated_execution = (
        await coordinator.execute_plan(
            plan=task_plan,
            state=state,
        )
    )

    updated_plan = coordinated_execution.plan

    # ==========================================================
    # Build deterministic post-wave execution snapshot
    # ==========================================================

    plan_execution_outcome = (
        build_plan_execution_outcome(
            task_plan=updated_plan,
            task_results=(
                coordinated_execution.task_results
            ),
        )
    )

    # ==========================================================
    # Wave finished
    # ==========================================================

    print()
    print("=" * 72)
    print("              CONCURRENT WAVE END")
    print("=" * 72)

    print()
    print("Wave results:")

    for result in coordinated_execution.task_results:

        print(
            f"  {result.task_id}"
            f" | status={result.status.value}"
            f" | processing_results="
            f"{len(result.processing_results)}"
        )

    newly_ready = [
        task
        for task in updated_plan.tasks
        if task.status.value == "ready"
    ]

    print()
    print(
        "READY tasks after reconciliation: "
        f"{[task.task_id for task in newly_ready]}"
    )

    print(
        "Plan condition after wave: "
        f"{plan_execution_outcome.condition.value}"
    )

    print(
        "Active memory after wave reconciliation:"
    )

    active_memory = state.get(
        "active_memory",
    )

    if active_memory is not None:

        print(
            f"  known_facts="
            f"{len(active_memory.known_facts)}"
        )

        print(
            f"  discovered_resources="
            f"{len(active_memory.discovered_resources)}"
        )

        print(
            f"  completed_work="
            f"{len(active_memory.completed_work)}"
        )

        print(
            f"  unresolved_needs="
            f"{len(active_memory.unresolved_needs)}"
        )

    else:

        print(
            "  WARNING: active_memory missing."
        )

    # ==========================================================
    # DETERMINE THE RUNTIME REVIEW BOUNDARY
    # ==========================================================
    #
    # This distinction is critical.
    #
    # A completed wave is not necessarily the end of the plan.
    #
    # Example:
    #
    #   Wave 1:
    #       A ──┐
    #       B ──┴─> completed
    #
    #   Reconciliation:
    #       C becomes READY
    #
    # In that case the runtime MUST enter REVIEWING through
    # EXECUTION_COMPLETED. The Critic gets the opportunity to
    # decide whether execution should continue.
    #
    # If the reconciliation instead leaves the entire TaskPlan
    # exhausted, we use PLAN_EXHAUSTED. This mirrors the legacy
    # runtime's semantic final-review boundary.
    # ==========================================================

    if TaskPlanManager.is_plan_complete(
        plan=updated_plan,
    ):
        transition_event = RuntimeEvent.PLAN_EXHAUSTED
    else:
        transition_event = RuntimeEvent.EXECUTION_COMPLETED

    # ==========================================================
    # MOVE RUNTIME INTO REVIEWING
    # ==========================================================

    next_stage = RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=transition_event,
    )

    print()
    print(
        "[CONCURRENT WAVE] Runtime transition:"
    )

    print(
        f"  event="
        f"{transition_event.value}"
    )

    print(
        f"  mode="
        f"{runtime_state.mode.value}"
    )

    print(
        f"  next_stage="
        f"{next_stage.value}"
    )

    print(
        f"  last_event="
        f"{runtime_state.last_event.value}"
    )

    # ==========================================================
    # AUTHORITATIVE GRAPH STATE PROPAGATION
    # ==========================================================
    #
    # The reconciler has already mutated these objects.
    # Return the authoritative post-wave state explicitly.
    # ==========================================================

    return {
        "task_plan": updated_plan,

        "plan_execution_outcome": (
            plan_execution_outcome
        ),

        "active_memory": state[
            "active_memory"
        ],

        "artifact_references": state[
            "artifact_references"
        ],

        "execution_memory": state[
            "execution_memory"
        ],

        "execution_workflow": None,

        "runtime_state": runtime_state,
    }