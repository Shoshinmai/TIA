from __future__ import annotations

from agents.terminal.runtime.dispatcher import RuntimeDispatcher
from agents.terminal.runtime.events import RuntimeEvent
from agents.terminal.runtime.models import (
    RuntimeDecisionContext,
    RuntimeEvidence,
    RuntimeState,
)
from agents.terminal.runtime.modes import RuntimeMode
from agents.terminal.runtime.stages import RuntimeStage
from agents.terminal.runtime.state_machine import RuntimeStateMachine


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
    
