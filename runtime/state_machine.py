from __future__ import annotations

from dataclasses import dataclass

from agents.terminal.runtime.events import RuntimeEvent
from agents.terminal.runtime.modes import RuntimeMode


@dataclass(frozen=True, slots=True)
class Transition:
    """
    A deterministic runtime transition.

    Represents:
        Current RuntimeMode
            +
        RuntimeEvent
            ->
        Next RuntimeMode
    """

    mode: RuntimeMode
    event: RuntimeEvent


# ---------------------------------------------------------------------
# Runtime Transition Table
# ---------------------------------------------------------------------

_TRANSITIONS: dict[Transition, RuntimeMode] = {
    # ================================================================
    # Initialization
    # ================================================================
    # Task initialization completed and the runtime is ready
    # to begin strategic planning.
    Transition(
        RuntimeMode.INITIALIZING,
        RuntimeEvent.TASK_READY,
    ): RuntimeMode.PLANNING,
    # ================================================================
    # Planning
    # ================================================================
    # Planner successfully created (or updated) a plan.
    Transition(
        RuntimeMode.PLANNING,
        RuntimeEvent.PLAN_CREATED,
    ): RuntimeMode.EXECUTING,
    Transition(
        RuntimeMode.PLANNING,
        RuntimeEvent.PLAN_UPDATED,
    ): RuntimeMode.EXECUTING,
    # Planner could not create a valid plan.
    Transition(
        RuntimeMode.PLANNING,
        RuntimeEvent.PLAN_FAILED,
    ): RuntimeMode.ERROR,
    Transition(
        RuntimeMode.PLANNING,
        RuntimeEvent.PLAN_CANCELLED,
    ): RuntimeMode.FINISHED,
    # ================================================================
    # Execution
    # ================================================================
    # Regardless of success/failure, execution must be reviewed.
    Transition(
        RuntimeMode.EXECUTING,
        RuntimeEvent.EXECUTION_COMPLETED,
    ): RuntimeMode.REVIEWING,
    Transition(
        RuntimeMode.EXECUTING,
        RuntimeEvent.EXECUTION_FAILED,
    ): RuntimeMode.REVIEWING,
    # ================================================================
    # Review
    # ================================================================
    # The current TaskPlan has no remaining objectives.
    # This does NOT mean the user's goal is necessarily complete.
    # Keep the runtime in REVIEWING so the Critic can make the
    # semantic GOAL_COMPLETED / REPLAN_REQUIRED decision.
    Transition(
        RuntimeMode.REVIEWING,
        RuntimeEvent.PLAN_EXHAUSTED,
    ): RuntimeMode.REVIEWING,
    # Critic decided the current objective is not finished,
    # but the existing execution approach remains valid.
    Transition(
        RuntimeMode.REVIEWING,
        RuntimeEvent.CONTINUE_TASK,
    ): RuntimeMode.EXECUTING,
    # Execution failed, but the current objective and strategy
    # remain valid enough for another execution attempt.
    Transition(
        RuntimeMode.REVIEWING,
        RuntimeEvent.RETRY_TASK,
    ): RuntimeMode.EXECUTING,
    # Current objective completed.
    #
    # The dispatcher / kernel will ask the TaskPlanManager
    # whether another objective exists.
    Transition(
        RuntimeMode.REVIEWING,
        RuntimeEvent.TASK_COMPLETED,
    ): RuntimeMode.EXECUTING,
    # New information requires the rolling Task Plan to be
    # extended or adjusted, while the overall strategy remains valid.
    Transition(
        RuntimeMode.REVIEWING,
        RuntimeEvent.PLAN_UPDATE_REQUIRED,
    ): RuntimeMode.PLANNING,
    # Current strategy or important assumptions are no longer valid.
    Transition(
        RuntimeMode.REVIEWING,
        RuntimeEvent.REPLAN_REQUIRED,
    ): RuntimeMode.PLANNING,
    # Whole user goal completed.
    Transition(
        RuntimeMode.REVIEWING,
        RuntimeEvent.GOAL_COMPLETED,
    ): RuntimeMode.FINISHED,
    # The current TaskPlan cannot make deterministic progress.
    #
    # Keep the runtime in REVIEWING so the Critic can determine
    # whether to retry, update the plan, or replan.
    Transition(
        RuntimeMode.REVIEWING,
        RuntimeEvent.TASK_BLOCKED,
    ): RuntimeMode.REVIEWING,
}


class InvalidRuntimeTransition(RuntimeError):
    """Raised when an invalid runtime transition is requested."""


class RuntimeStateMachine:
    """
    Deterministic runtime state machine.

    Responsibilities:
        - Validate runtime transitions.
        - Determine the next runtime mode.

    Responsibilities it does NOT have:
        - Execute nodes
        - Invoke the LLM
        - Mutate runtime state
        - Know about LangGraph
    """

    @classmethod
    def transition(
        cls,
        *,
        current_mode: RuntimeMode,
        event: RuntimeEvent,
    ) -> RuntimeMode:
        transition = Transition(
            mode=current_mode,
            event=event,
        )

        try:
            return _TRANSITIONS[transition]

        except KeyError as exc:
            raise InvalidRuntimeTransition(
                f"Invalid runtime transition: "
                f"{current_mode.value} --({event.value})-> ?"
            ) from exc

    @classmethod
    def can_transition(
        cls,
        *,
        current_mode: RuntimeMode,
        event: RuntimeEvent,
    ) -> bool:
        return (
            Transition(
                current_mode,
                event,
            )
            in _TRANSITIONS
        )

    @classmethod
    def valid_events(
        cls,
        mode: RuntimeMode,
    ) -> tuple[RuntimeEvent, ...]:
        return tuple(
            transition.event for transition in _TRANSITIONS if transition.mode == mode
        )


import pytest


def test_plan_update_required():
    assert (
        RuntimeStateMachine.transition(
            current_mode=RuntimeMode.REVIEWING,
            event=RuntimeEvent.PLAN_UPDATE_REQUIRED,
        )
        == RuntimeMode.PLANNING
    )


def test_replan_required():
    assert (
        RuntimeStateMachine.transition(
            current_mode=RuntimeMode.REVIEWING,
            event=RuntimeEvent.REPLAN_REQUIRED,
        )
        == RuntimeMode.PLANNING
    )


def test_plan_update_and_replan_have_same_runtime_mode():
    plan_update_mode = RuntimeStateMachine.transition(
        current_mode=RuntimeMode.REVIEWING,
        event=RuntimeEvent.PLAN_UPDATE_REQUIRED,
    )

    replan_mode = RuntimeStateMachine.transition(
        current_mode=RuntimeMode.REVIEWING,
        event=RuntimeEvent.REPLAN_REQUIRED,
    )

    assert plan_update_mode == RuntimeMode.PLANNING
    assert replan_mode == RuntimeMode.PLANNING


def test_invalid_runtime_transition():
    with pytest.raises(InvalidRuntimeTransition):
        RuntimeStateMachine.transition(
            current_mode=RuntimeMode.FINISHED,
            event=RuntimeEvent.RETRY_TASK,
        )


def test_can_transition():
    assert RuntimeStateMachine.can_transition(
        current_mode=RuntimeMode.REVIEWING,
        event=RuntimeEvent.PLAN_UPDATE_REQUIRED,
    )

    assert not RuntimeStateMachine.can_transition(
        current_mode=RuntimeMode.FINISHED,
        event=RuntimeEvent.RETRY_TASK,
    )


def test_task_ready_starts_planning():
    assert (
        RuntimeStateMachine.transition(
            current_mode=RuntimeMode.INITIALIZING,
            event=RuntimeEvent.TASK_READY,
        )
        == RuntimeMode.PLANNING
    )


def test_initializing_can_accept_task_ready():
    assert RuntimeStateMachine.can_transition(
        current_mode=RuntimeMode.INITIALIZING,
        event=RuntimeEvent.TASK_READY,
    )


def test_initializing_cannot_accept_plan_created():
    assert not RuntimeStateMachine.can_transition(
        current_mode=RuntimeMode.INITIALIZING,
        event=RuntimeEvent.PLAN_CREATED,
    )


def test_plan_exhausted_keeps_runtime_in_reviewing():
    assert (
        RuntimeStateMachine.transition(
            current_mode=RuntimeMode.REVIEWING,
            event=RuntimeEvent.PLAN_EXHAUSTED,
        )
        == RuntimeMode.REVIEWING
    )


def test_plan_exhausted_is_valid_from_reviewing():
    assert RuntimeStateMachine.can_transition(
        current_mode=RuntimeMode.REVIEWING,
        event=RuntimeEvent.PLAN_EXHAUSTED,
    )
