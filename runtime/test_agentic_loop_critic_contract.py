import pytest
from pydantic import ValidationError

from runtime.agentic_loop_critic_models import (
    CriticAdvice,
    CriticConsultationRequest,
    CriticDialogueContext,
    CriticDialogueTurn,
    DialogueSpeaker,
    ObservationRecord,
    ObservationSource,
)
from runtime.agentic_loop_critic_policy import CriticInvocationPolicy


def test_observation_preserves_source_and_content():
    observation = ObservationRecord(
        sequence=1,
        source=ObservationSource.CAPABILITY,
        source_name="search_files",
        content="Found two matching files.",
    )

    assert observation.source == ObservationSource.CAPABILITY
    assert observation.source_name == "search_files"
    assert observation.content == "Found two matching files."


def test_observation_rejects_oversized_content():
    with pytest.raises(ValidationError):
        ObservationRecord(
            sequence=1,
            source=ObservationSource.RUNTIME,
            content="x" * 1_501,
        )


def test_consultation_requires_goal_and_question():
    with pytest.raises(ValidationError):
        CriticConsultationRequest(
            goal=" ",
            question="What should I investigate next?",
        )


def test_consultation_keeps_observations_separate_from_advice():
    observation = ObservationRecord(
        sequence=1,
        source=ObservationSource.CAPABILITY,
        source_name="read_file",
        content="The file contains a configuration setting.",
    )

    request = CriticConsultationRequest(
        goal="Understand the configuration.",
        question="What should I inspect next?",
        relevant_observations=[observation],
        proposed_approach="Inspect references to the setting.",
    )

    assert request.relevant_observations == [observation]
    assert request.proposed_approach is not None
    assert not hasattr(observation, "advice")


def test_dialogue_context_retains_summary_and_recent_exchange():
    context = CriticDialogueContext(
        summary="Earlier discussion considered two possible approaches.",
        recent_exchange=[
            CriticDialogueTurn(
                speaker=DialogueSpeaker.MAIN_AGENT,
                content="Would inspecting the caller clarify this?",
            ),
            CriticDialogueTurn(
                speaker=DialogueSpeaker.CRITIC,
                content="Yes; the caller should establish how the value is used.",
            ),
        ],
    )

    assert len(context.recent_exchange) == 2
    assert context.recent_exchange[0].speaker == DialogueSpeaker.MAIN_AGENT
    assert context.recent_exchange[1].speaker == DialogueSpeaker.CRITIC


def test_dialogue_rejects_misordered_two_turn_exchange():
    with pytest.raises(ValidationError):
        CriticDialogueContext(
            recent_exchange=[
                CriticDialogueTurn(
                    speaker=DialogueSpeaker.CRITIC,
                    content="Inspect the caller.",
                ),
                CriticDialogueTurn(
                    speaker=DialogueSpeaker.MAIN_AGENT,
                    content="I will do that.",
                ),
            ],
        )


def test_critic_advice_can_express_uncertainty_and_follow_up():
    advice = CriticAdvice(
        advice="Inspect the caller before changing the configuration.",
        uncertainty="The current evidence does not show how the value is consumed.",
        follow_up_question="Have you already located the caller?",
    )

    assert advice.uncertainty is not None
    assert advice.follow_up_question is not None


def test_critic_advice_does_not_require_a_pass_fail_decision():
    advice = CriticAdvice(
        advice="I recommend inspecting the caller, but the evidence is incomplete.",
    )

    assert advice.advice
    assert not hasattr(advice, "decision")


def test_critic_is_not_invoked_without_explicit_request():
    policy = CriticInvocationPolicy()

    assert not policy.can_consult(
        main_agent_requested=False,
        responses_this_consultation=0,
        responses_this_run=0,
    )


def test_critic_can_be_invoked_when_requested_and_within_budgets():
    policy = CriticInvocationPolicy()

    assert policy.can_consult(
        main_agent_requested=True,
        responses_this_consultation=0,
        responses_this_run=0,
    )


def test_consultation_budget_is_enforced():
    policy = CriticInvocationPolicy(
        max_responses_per_consultation=2,
        max_responses_per_run=5,
    )

    assert not policy.can_consult(
        main_agent_requested=True,
        responses_this_consultation=2,
        responses_this_run=2,
    )

    assert (
        policy.exhausted_reason(
            responses_this_consultation=2,
            responses_this_run=2,
        )
        == "consultation_limit"
    )


def test_run_budget_is_enforced_across_consultations():
    policy = CriticInvocationPolicy(
        max_responses_per_consultation=3,
        max_responses_per_run=4,
    )

    assert not policy.can_consult(
        main_agent_requested=True,
        responses_this_consultation=1,
        responses_this_run=4,
    )

    assert (
        policy.exhausted_reason(
            responses_this_consultation=1,
            responses_this_run=4,
        )
        == "run_limit"
    )


def test_negative_counters_do_not_allow_consultation():
    policy = CriticInvocationPolicy()

    assert not policy.can_consult(
        main_agent_requested=True,
        responses_this_consultation=-1,
        responses_this_run=0,
    )