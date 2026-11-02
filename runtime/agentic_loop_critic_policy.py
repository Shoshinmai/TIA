from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CriticInvocationPolicy:
    """Policy for reactive critic consultations.

    The main agent must explicitly request advice. There is no automatic
    or proactive critic invocation. The critic is advisory.
    """

    def can_consult(
        self,
        *,
        main_agent_requested: bool,
        responses_this_consultation: int = 0,
        responses_this_run: int = 0,
    ) -> bool:
        """Return whether another critic response is permitted.

        A consultation is allowed only when explicitly requested by the
        main agent.
        """
        return main_agent_requested