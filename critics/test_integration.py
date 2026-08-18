import pytest

from agents.terminal.critics.integration import (
    critic_output_to_runtime_event,
    build_critic_runtime_event,
)

from agents.terminal.critics.models import (
    CriticDecision,
    CriticEvidence,
    CriticOutput,
)

from agents.terminal.runtime.events import RuntimeEvent
from agents.terminal.runtime.kernel import RuntimeKernel
from agents.terminal.runtime.models import RuntimeState
from agents.terminal.runtime.modes import RuntimeMode


@pytest.fixture
def critic_evidence():
    return [
        CriticEvidence(
            source="execution",
            observation="The execution result provides sufficient evidence.",
        )
    ]


@pytest.mark.parametrize(
    "decision, expected_event",
    [
        (
            CriticDecision.CONTINUE_TASK,
            RuntimeEvent.CONTINUE_TASK,
        ),
        (
            CriticDecision.TASK_COMPLETED,
            RuntimeEvent.TASK_COMPLETED,
        ),
        (
            CriticDecision.RETRY_TASK,
            RuntimeEvent.RETRY_TASK,
        ),
        (
            CriticDecision.PLAN_UPDATE_REQUIRED,
            RuntimeEvent.PLAN_UPDATE_REQUIRED,
        ),
        (
            CriticDecision.REPLAN_REQUIRED,
            RuntimeEvent.REPLAN_REQUIRED,
        ),
        (
            CriticDecision.GOAL_COMPLETED,
            RuntimeEvent.GOAL_COMPLETED,
        ),
    ],
)
def test_every_critic_decision_maps_to_runtime_event(
    decision,
    expected_event,
    critic_evidence,
):

    critic_output = CriticOutput(
        decision=decision,
        rationale="Test rationale.",
        evidence=critic_evidence,
    )

    event = critic_output_to_runtime_event(
        critic_output,
    )

    assert event == expected_event
    
def test_critic_runtime_event_preserves_decision_context():

    critic_output = CriticOutput(
        decision=CriticDecision.RETRY_TASK,
        rationale="The previous execution failed because the path was incorrect.",
        evidence=[
            CriticEvidence(
                source="execution",
                observation="The requested file was found at a different path.",
            )
        ],
    )

    runtime_event = build_critic_runtime_event(
        critic_output,
    )

    assert (
        runtime_event.event
        == RuntimeEvent.RETRY_TASK
    )

    assert (
        runtime_event.context.rationale
        == critic_output.rationale
    )

    assert len(
        runtime_event.context.evidence
    ) == 1

    assert (
        runtime_event.context.evidence[0].source
        == "execution"
    )

    assert (
        runtime_event.context.evidence[0].observation
        == "The requested file was found at a different path."
    )
    
@pytest.mark.parametrize(
    "event, expected_mode",
    [
        (
            RuntimeEvent.CONTINUE_TASK,
            RuntimeMode.EXECUTING,
        ),
        (
            RuntimeEvent.TASK_COMPLETED,
            RuntimeMode.EXECUTING,
        ),
        (
            RuntimeEvent.RETRY_TASK,
            RuntimeMode.EXECUTING,
        ),
        (
            RuntimeEvent.PLAN_UPDATE_REQUIRED,
            RuntimeMode.PLANNING,
        ),
        (
            RuntimeEvent.REPLAN_REQUIRED,
            RuntimeMode.PLANNING,
        ),
        (
            RuntimeEvent.GOAL_COMPLETED,
            RuntimeMode.FINISHED,
        ),
    ],
)
def test_critic_decision_runtime_transitions(
    event,
    expected_mode,
):

    runtime_state = RuntimeState(
        mode=RuntimeMode.REVIEWING,
    )

    RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=event,
    )

    assert (
        runtime_state.mode
        == expected_mode
    )