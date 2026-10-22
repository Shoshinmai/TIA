from __future__ import annotations

from nodes.task_initializer import task_initializer_node
from runtime.agentic_loop_critic_models import (
    CriticConsultationState,
    ObservationRecord,
    ObservationSource,
)
from runtime.agentic_loop_models import (
    AgenticLoopAction,
    AgenticLoopDecision,
    AgenticLoopResult,
    AgenticLoopStatus,
)
from models import ThreadMemory


def _config() -> dict:
    return {"configurable": {"thread_id": "thread-123"}}


def test_task_initializer_creates_fresh_agentic_loop_state(tmp_path):
    thread_memory = ThreadMemory()
    state = {
        "goal": "Inspect a project",
        "workspace": str(tmp_path),
        "thread_memory": thread_memory,
    }

    initialized = task_initializer_node(state, _config())

    assert initialized["agentic_loop_decision"] is None
    assert initialized["agentic_loop_observations"] == []
    assert initialized["agentic_loop_critic_state"] == CriticConsultationState()
    assert initialized["agentic_loop_recent_actions"] == []
    assert initialized["agentic_loop_decisions_made"] == 0
    assert initialized["agentic_loop_critic_responses_received"] == 0
    assert initialized["agentic_loop_result"] is None
    assert initialized["thread_memory"] is thread_memory


def test_task_initializer_resets_agentic_loop_state_for_next_task(tmp_path):
    previous_decision = AgenticLoopDecision(
        action=AgenticLoopAction.FINISH,
        rationale="Previously finished.",
        final_response="Previous result.",
    )
    previous_result = AgenticLoopResult(
        status=AgenticLoopStatus.FINISHED,
        final_response="Previous result.",
    )
    previous_state = {
        "goal": "A new task",
        "workspace": str(tmp_path),
        "thread_memory": ThreadMemory(),
        "agentic_loop_decision": previous_decision,
        "agentic_loop_observations": [
            ObservationRecord(
                sequence=1,
                source=ObservationSource.CAPABILITY,
                source_name="list_directory",
                content="Previous task observation.",
            )
        ],
        "agentic_loop_critic_state": CriticConsultationState(
            responses_received=1,
            dialogue_summary="Previous task advice.",
        ),
        "agentic_loop_recent_actions": ["Previous action"],
        "agentic_loop_decisions_made": 4,
        "agentic_loop_critic_responses_received": 1,
        "agentic_loop_result": previous_result,
    }

    initialized = task_initializer_node(previous_state, _config())

    assert initialized["agentic_loop_decision"] is None
    assert initialized["agentic_loop_observations"] == []
    assert initialized["agentic_loop_critic_state"].responses_received == 0
    assert initialized["agentic_loop_critic_state"].dialogue_summary == ""
    assert initialized["agentic_loop_recent_actions"] == []
    assert initialized["agentic_loop_decisions_made"] == 0
    assert initialized["agentic_loop_critic_responses_received"] == 0
    assert initialized["agentic_loop_result"] is None


def test_agentic_loop_collections_are_not_shared_between_initializations(tmp_path):
    state = {"goal": "Inspect", "workspace": str(tmp_path)}
    first = task_initializer_node(state, _config())
    second = task_initializer_node(state, _config())

    first["agentic_loop_observations"].append(
        ObservationRecord(
            sequence=1,
            source=ObservationSource.OTHER,
            content="Only in the first task.",
        )
    )
    first["agentic_loop_recent_actions"].append("first action")

    assert second["agentic_loop_observations"] == []
    assert second["agentic_loop_recent_actions"] == []
