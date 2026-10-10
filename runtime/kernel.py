from __future__ import annotations

from runtime.dispatcher import RuntimeDispatcher
from runtime.events import RuntimeEvent
from runtime.models import (
    RuntimeDecisionContext,
    RuntimeEvidence,
    RuntimeState,
)
from runtime.modes import RuntimeMode
from runtime.stages import RuntimeStage
from runtime.state_machine import RuntimeStateMachine


class RuntimeKernel:
    """
    Public facade for the Terminal Agent Runtime.

    Responsibilities
    ----------------
    - Own RuntimeState mutations.
    - Validate runtime transitions.
    - Determine the next runtime stage.
    - Preserve runtime decision context across transitions.

    It intentionally knows nothing about:
        - LangGraph
        - Planner implementation
        - Executor implementation
        - Critic implementation
        - Tool execution
    """

    # Terminal reasons for incomplete completion
    TERMINAL_REASON_GOAL_COMPLETION_REJECTED = "goal_completion_rejected"
    TERMINAL_REASON_BUDGET_EXHAUSTED = "budget_exhausted"
    TERMINAL_REASON_PARTIAL_COMPLETION = "partial_completion"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def handle_event(
        cls,
        *,
        runtime_state: RuntimeState,
        event: RuntimeEvent,
        decision_context: RuntimeDecisionContext | None = None,
    ) -> RuntimeStage:
        """
        Process a runtime event and return the next runtime stage.
        """

        next_mode = RuntimeStateMachine.transition(
            current_mode=runtime_state.mode,
            event=event,
        )

        cls._update_runtime_state(
            runtime_state=runtime_state,
            next_mode=next_mode,
            event=event,
            decision_context=decision_context,
        )

        return RuntimeDispatcher.dispatch(
            next_mode
        )

    @classmethod
    def handle_event_with_termination(
        cls,
        *,
        runtime_state: RuntimeState,
        event: RuntimeEvent,
        decision_context: RuntimeDecisionContext | None = None,
        termination_reason: str | None = None,
    ) -> RuntimeStage:
        """
        Process a runtime event with an explicit termination reason.
        Used when budget exhaustion or goal rejection forces terminal state.
        """
        if termination_reason is not None:
            runtime_state.metadata["termination_reason"] = termination_reason

        next_mode = RuntimeStateMachine.transition(
            current_mode=runtime_state.mode,
            event=event,
        )

        cls._update_runtime_state(
            runtime_state=runtime_state,
            next_mode=next_mode,
            event=event,
            decision_context=decision_context,
        )

        return RuntimeDispatcher.dispatch(
            next_mode
        )

    @classmethod
    def current_stage(
        cls,
        *,
        runtime_state: RuntimeState,
    ) -> RuntimeStage:
        """
        Return the subsystem that currently owns execution.
        """

        return RuntimeDispatcher.dispatch(
            runtime_state.mode
        )

    @classmethod
    def reset(
        cls,
        *,
        runtime_state: RuntimeState,
    ) -> None:
        """
        Reset the runtime to its initial state.
        """

        runtime_state.mode = RuntimeMode.INITIALIZING
        runtime_state.last_event = None
        runtime_state.iteration = 0
        runtime_state.decision_context = None
        runtime_state.metadata.pop("termination_reason", None)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _update_runtime_state(
        *,
        runtime_state: RuntimeState,
        next_mode: RuntimeMode,
        event: RuntimeEvent,
        decision_context: RuntimeDecisionContext | None,
    ) -> None:
        """
        Apply deterministic RuntimeState mutations.

        This is the only place where RuntimeState is mutated.
        """

        runtime_state.mode = next_mode
        runtime_state.last_event = event
        runtime_state.iteration += 1
        runtime_state.decision_context = decision_context

        # Track decision history for loop detection
        if decision_context is not None:
            decision_entry = {
                "event": event.value,
                "rationale_hash": hash(decision_context.rationale),
                "target_task_ids": list(decision_context.target_task_ids),
                "decision_scope": decision_context.decision_scope,
                "iteration": runtime_state.iteration,
            }
            runtime_state.decision_history.append(decision_entry)
            # Trim history to max size
            if len(runtime_state.decision_history) > runtime_state.max_decision_history:
                runtime_state.decision_history = runtime_state.decision_history[-runtime_state.max_decision_history:]

    @classmethod
    def check_budget_exhaustion(
        cls,
        runtime_state: RuntimeState,
        plan_execution_outcome: Any | None = None,
    ) -> tuple[bool, str | None]:
        """
        Check if any budget has been exhausted.

        Returns tuple of (exhausted, termination_reason).
        """
        # Check iteration budget
        if runtime_state.iteration >= runtime_state.max_iterations:
            return True, cls.TERMINAL_REASON_BUDGET_EXHAUSTED

        # Check no-progress budget
        # A wave makes "no progress" if it executed 0 tasks or all tasks failed
        # without producing new evidence. This is a heuristic.
        if runtime_state.consecutive_no_progress >= runtime_state.max_no_progress:
            return True, cls.TERMINAL_REASON_BUDGET_EXHAUSTED

        # Check for repeated decisions (simple heuristic: same event + same targets + same rationale_hash in recent history)
        if len(runtime_state.decision_history) >= 3:
            recent = runtime_state.decision_history[-3:]
            if len(recent) == 3:
                first = recent[0]
                if all(
                    d["event"] == first["event"]
                    and d["target_task_ids"] == first["target_task_ids"]
                    and d["rationale_hash"] == first["rationale_hash"]
                    for d in recent
                ):
                    # Same decision repeated 3 times
                    return True, cls.TERMINAL_REASON_BUDGET_EXHAUSTED

        return False, None

    @classmethod
    def record_wave_progress(
        cls,
        runtime_state: RuntimeState,
        wave_executed_tasks: int,
        plan_execution_outcome: Any | None = None,
    ) -> None:
        """
        Record progress from an execution wave for budget tracking.

        Resets consecutive_no_progress if meaningful progress was made.
        """
        # Determine if meaningful progress was made
        made_progress = False
        if wave_executed_tasks > 0:
            # At least one task was executed
            if plan_execution_outcome is not None:
                # Check if any task completed successfully
                if plan_execution_outcome.completed_task_ids:
                    made_progress = True
                # Check if new evidence was produced (simplified)
                elif plan_execution_outcome.task_results:
                    made_progress = True

        if made_progress:
            runtime_state.consecutive_no_progress = 0
        else:
            runtime_state.consecutive_no_progress += 1
        


def test_kernel_handles_execution_completed():
    runtime_state = RuntimeState(
        mode=RuntimeMode.EXECUTING,
    )

    stage = RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=RuntimeEvent.EXECUTION_COMPLETED,
    )

    assert runtime_state.mode == RuntimeMode.REVIEWING
    assert runtime_state.last_event == RuntimeEvent.EXECUTION_COMPLETED
    assert runtime_state.iteration == 1
    assert runtime_state.decision_context is None

    assert stage == RuntimeStage.CRITIC
    
def test_kernel_handles_retry_with_context():
    runtime_state = RuntimeState(
        mode=RuntimeMode.REVIEWING,
    )

    context = RuntimeDecisionContext(
        rationale="The failure is recoverable.",
        evidence=[
            RuntimeEvidence(
                source="execution",
                observation="The target process was temporarily unavailable.",
            )
        ],
    )

    stage = RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=RuntimeEvent.RETRY_TASK,
        decision_context=context,
    )

    assert runtime_state.mode == RuntimeMode.EXECUTING
    assert runtime_state.last_event == RuntimeEvent.RETRY_TASK
    assert runtime_state.decision_context == context

    assert stage == RuntimeStage.EXECUTOR
    
def test_kernel_handles_replan_with_context():
    runtime_state = RuntimeState(
        mode=RuntimeMode.REVIEWING,
    )

    context = RuntimeDecisionContext(
        rationale="The current strategy is no longer valid.",
        evidence=[
            RuntimeEvidence(
                source="execution",
                observation="The expected implementation does not exist.",
            )
        ],
    )

    stage = RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=RuntimeEvent.REPLAN_REQUIRED,
        decision_context=context,
    )

    assert runtime_state.mode == RuntimeMode.PLANNING
    assert runtime_state.last_event == RuntimeEvent.REPLAN_REQUIRED
    assert runtime_state.decision_context == context

    assert stage == RuntimeStage.PLANNER
    
def test_kernel_handles_plan_update():
    runtime_state = RuntimeState(
        mode=RuntimeMode.REVIEWING,
    )

    context = RuntimeDecisionContext(
        rationale="New information requires extending the rolling plan.",
        evidence=[
            RuntimeEvidence(
                source="execution",
                observation="A previously unknown dependency was discovered.",
            )
        ],
    )

    stage = RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=RuntimeEvent.PLAN_UPDATE_REQUIRED,
        decision_context=context,
    )

    assert runtime_state.mode == RuntimeMode.PLANNING
    assert runtime_state.decision_context == context
    assert stage == RuntimeStage.PLANNER
    
