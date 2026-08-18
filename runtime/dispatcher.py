from __future__ import annotations

from agents.terminal.runtime.modes import RuntimeMode
from agents.terminal.runtime.stages import RuntimeStage


class InvalidRuntimeDispatch(RuntimeError):
    """Raised when no runtime stage is registered for a runtime mode."""


_MODE_TO_STAGE = {
    RuntimeMode.INITIALIZING: RuntimeStage.PLANNER,

    RuntimeMode.PLANNING: RuntimeStage.PLANNER,

    RuntimeMode.EXECUTING: RuntimeStage.EXECUTOR,

    RuntimeMode.REVIEWING: RuntimeStage.CRITIC,

    RuntimeMode.FINISHED: RuntimeStage.TERMINATE,

    RuntimeMode.ERROR: RuntimeStage.ERROR,
}


class RuntimeDispatcher:
    """
    Maps runtime modes to subsystem stages.

    It performs no orchestration and no reasoning.
    """

    @classmethod
    def dispatch(
        cls,
        mode: RuntimeMode,
    ) -> RuntimeStage:

        try:
            return _MODE_TO_STAGE[mode]

        except KeyError as exc:
            raise InvalidRuntimeDispatch(
                f"No dispatcher registered for runtime mode: "
                f"{mode.value}"
            ) from exc

    @classmethod
    def owns_stage(
        cls,
        *,
        mode: RuntimeMode,
        stage: RuntimeStage,
    ) -> bool:
        return cls.dispatch(mode) == stage
   
   
    
def test_initializing_dispatches_to_planner():
    assert (
        RuntimeDispatcher.dispatch(RuntimeMode.INITIALIZING)
        == RuntimeStage.PLANNER
    )


def test_planning_dispatches_to_planner():
    assert (
        RuntimeDispatcher.dispatch(RuntimeMode.PLANNING)
        == RuntimeStage.PLANNER
    )


def test_executing_dispatches_to_executor():
    assert (
        RuntimeDispatcher.dispatch(RuntimeMode.EXECUTING)
        == RuntimeStage.EXECUTOR
    )


def test_reviewing_dispatches_to_critic():
    assert (
        RuntimeDispatcher.dispatch(RuntimeMode.REVIEWING)
        == RuntimeStage.CRITIC
    )


def test_finished_dispatches_to_terminate():
    assert (
        RuntimeDispatcher.dispatch(RuntimeMode.FINISHED)
        == RuntimeStage.TERMINATE
    )


def test_error_dispatches_to_error():
    assert (
        RuntimeDispatcher.dispatch(RuntimeMode.ERROR)
        == RuntimeStage.ERROR
    )
    
def test_owns_stage():
    assert RuntimeDispatcher.owns_stage(
        mode=RuntimeMode.PLANNING,
        stage=RuntimeStage.PLANNER,
    )

    assert not RuntimeDispatcher.owns_stage(
        mode=RuntimeMode.PLANNING,
        stage=RuntimeStage.EXECUTOR,
    )