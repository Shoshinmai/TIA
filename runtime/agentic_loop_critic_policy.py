from __future__ import annotations

from dataclasses import dataclass


DEFAULT_MAX_CRITIC_RESPONSES_PER_CONSULTATION = 3
DEFAULT_MAX_CRITIC_RESPONSES_PER_RUN = 8


@dataclass(frozen=True, slots=True)
class CriticInvocationPolicy:
    """Limits for reactive critic consultations.

    The main agent must explicitly request advice. There is no automatic
    or proactive critic invocation in this initial version.
    """

    max_responses_per_consultation: int = (
        DEFAULT_MAX_CRITIC_RESPONSES_PER_CONSULTATION
    )
    max_responses_per_run: int = DEFAULT_MAX_CRITIC_RESPONSES_PER_RUN

    def __post_init__(self) -> None:
        if self.max_responses_per_consultation < 1:
            raise ValueError(
                "max_responses_per_consultation must be at least 1."
            )

        if self.max_responses_per_run < 1:
            raise ValueError("max_responses_per_run must be at least 1.")

        if (
            self.max_responses_per_consultation
            > self.max_responses_per_run
        ):
            raise ValueError(
                "The per-consultation response limit cannot exceed "
                "the per-run response limit."
            )

    def can_consult(
        self,
        *,
        main_agent_requested: bool,
        responses_this_consultation: int,
        responses_this_run: int,
    ) -> bool:
        """Return whether another critic response is permitted.

        A consultation is allowed only when explicitly requested and both
        response budgets have remaining capacity.
        """
        if not main_agent_requested:
            return False

        if responses_this_consultation < 0 or responses_this_run < 0:
            return False

        if (
            responses_this_consultation
            >= self.max_responses_per_consultation
        ):
            return False

        if responses_this_run >= self.max_responses_per_run:
            return False

        return True

    def exhausted_reason(
        self,
        *,
        responses_this_consultation: int,
        responses_this_run: int,
    ) -> str | None:
        """Explain which limit prevents another critic response.

        The caller should check this only after the main agent requests
        a consultation. Lack of a request is not budget exhaustion.
        """
        if (
            responses_this_consultation
            >= self.max_responses_per_consultation
        ):
            return "consultation_limit"

        if responses_this_run >= self.max_responses_per_run:
            return "run_limit"

        return None