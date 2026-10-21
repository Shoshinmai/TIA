from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


MAX_OBSERVATION_CHARS = 1_500
MAX_OBSERVATIONS_PER_CONTEXT = 10
MAX_DIALOGUE_SUMMARY_CHARS = 3_000
MAX_DIALOGUE_TURN_CHARS = 2_500
MAX_RECENT_DIALOGUE_TURNS = 3
MAX_RECENT_ACTIONS = 5


class ObservationSource(StrEnum):
    """Origin of a factual observation."""

    CAPABILITY = "capability"
    RUNTIME = "runtime"
    USER = "user"
    OTHER = "other"


class ObservationRecord(BaseModel):
    """A bounded record of something actually observed.

    This model stores reported results, not conclusions or advice.
    The source identifies where the observation came from.
    """

    sequence: int = Field(ge=1)
    source: ObservationSource
    source_name: str = Field(default="", max_length=200)
    content: str = Field(min_length=1, max_length=MAX_OBSERVATION_CHARS)

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if not self.content.strip():
            raise ValueError("Observation content must not be blank.")
        return self


class DialogueSpeaker(StrEnum):
    MAIN_AGENT = "main_agent"
    CRITIC = "critic"


class CriticDialogueTurn(BaseModel):
    """One bounded message in the critic consultation."""

    speaker: DialogueSpeaker
    content: str = Field(
        min_length=1,
        max_length=MAX_DIALOGUE_TURN_CHARS,
    )

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if not self.content.strip():
            raise ValueError("Dialogue content must not be blank.")
        return self


class CriticDialogueContext(BaseModel):
    """Bounded memory for continuing a critic consultation.

    Keep a compact summary of earlier turns and at most the most recent
    exchange: one main-agent message and one critic response.
    """

    summary: str = Field(
        default="",
        max_length=MAX_DIALOGUE_SUMMARY_CHARS,
    )
    recent_exchange: list[CriticDialogueTurn] = Field(
        default_factory=list,
        max_length=MAX_RECENT_DIALOGUE_TURNS,
    )

    @model_validator(mode="after")
    def validate_recent_exchange(self) -> Self:
        if len(self.recent_exchange) == 2:
            first, second = self.recent_exchange
            if (
                first.speaker != DialogueSpeaker.MAIN_AGENT
                or second.speaker != DialogueSpeaker.CRITIC
            ):
                raise ValueError(
                    "A two-turn recent exchange must contain the "
                    "main-agent message followed by the critic response."
                )
        return self


class CriticConsultationRequest(BaseModel):
    """Information the main agent chooses to send to the critic."""

    goal: str = Field(min_length=1, max_length=4_000)
    question: str = Field(min_length=1, max_length=2_000)

    relevant_observations: list[ObservationRecord] = Field(
        default_factory=list,
        max_length=MAX_OBSERVATIONS_PER_CONTEXT,
    )
    recent_actions: list[str] = Field(
        default_factory=list,
        max_length=MAX_RECENT_ACTIONS,
    )
    proposed_approach: str | None = Field(
        default=None,
        max_length=2_000,
    )
    dialogue_context: CriticDialogueContext = Field(
        default_factory=CriticDialogueContext,
    )

    @model_validator(mode="after")
    def validate_required_text(self) -> Self:
        if not self.goal.strip():
            raise ValueError("The consultation goal must not be blank.")
        if not self.question.strip():
            raise ValueError("The consultation question must not be blank.")
        if self.proposed_approach is not None:
            if not self.proposed_approach.strip():
                self.proposed_approach = None
        return self


class CriticAdvice(BaseModel):
    """Conversational advice returned by the critic.

    This is deliberately not a pass/fail/retry decision. The main agent
    interprets the advice and chooses its own next action.
    """

    advice: str = Field(min_length=1, max_length=4_000)
    uncertainty: str | None = Field(
        default=None,
        max_length=1_500,
        description=(
            "What the critic is uncertain about, if anything."
        ),
    )
    follow_up_question: str | None = Field(
        default=None,
        max_length=1_500,
        description=(
            "An optional question the critic needs answered to advise "
            "more accurately."
        ),
    )

    @model_validator(mode="after")
    def validate_text(self) -> Self:
        if not self.advice.strip():
            raise ValueError("Critic advice must not be blank.")

        if self.uncertainty is not None and not self.uncertainty.strip():
            self.uncertainty = None

        if (
            self.follow_up_question is not None
            and not self.follow_up_question.strip()
        ):
            self.follow_up_question = None

        return self


class CriticConsultationStatus(StrEnum):
    OPEN = "open"
    ENDED_BY_MAIN_AGENT = "ended_by_main_agent"
    TURN_LIMIT_REACHED = "turn_limit_reached"
    RUN_BUDGET_EXHAUSTED = "run_budget_exhausted"
    CRITIC_UNAVAILABLE = "critic_unavailable"


class CriticConsultationState(BaseModel):
    """State for one consultation, separate from the main-loop budget."""

    status: CriticConsultationStatus = CriticConsultationStatus.OPEN
    responses_received: int = Field(default=0, ge=0)
    dialogue_summary: str = Field(
        default="",
        max_length=MAX_DIALOGUE_SUMMARY_CHARS,
    )
    recent_exchange: list[CriticDialogueTurn] = Field(
        default_factory=list,
        max_length=MAX_RECENT_DIALOGUE_TURNS,
    )
    last_advice: CriticAdvice | None = None