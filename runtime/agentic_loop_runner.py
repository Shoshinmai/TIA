
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from llm.llmclient import call_nvidia
from prompts.agentic_loop_prompt import AGENTIC_LOOP_PROMPT
from runtime.agentic_loop_context import (
    MAX_OBSERVATION_CHARS,
    MAX_OBSERVATION_COUNT,
    build_agentic_loop_context,
)
from runtime.agentic_loop_models import (
    AgenticLoopAction,
    AgenticLoopDecision,
    AgenticLoopResult,
    AgenticLoopStatus,
)
from tools import TOOLS


DEFAULT_AGENTIC_LOOP_MODEL = "nvidia/nemotron-3-super-120b-a12b"

DEFAULT_MAX_DECISIONS = 10
MAX_ALLOWED_DECISIONS = 50

_OBSERVATION_TRUNCATION_MARKER = "\n...[observation truncated]"


async def run_agentic_loop(
    state: Mapping[str, Any],
    *,
    goal: str | None = None,
    observations: Sequence[str] | None = None,
    capabilities: Sequence[Any] | None = None,
    model: str = DEFAULT_AGENTIC_LOOP_MODEL,
    max_decisions: int = DEFAULT_MAX_DECISIONS,
) -> AgenticLoopResult:
    """Run the autonomous problem-solving loop independently of the graph.

    Each iteration asks the LLM for one structured decision. CAPABILITY
    decisions execute the selected registered tool and append its observed
    result. FINISH, COMPLEX_EXECUTION, and CLARIFICATION stop the invocation.

    This runner does not mutate the supplied state, invoke the existing
    complex-execution subsystem, or certify that a reported goal is complete.

    Args:
        state: Current state mapping used by the Step 3 context builder.
        goal: Optional explicit original goal.
        observations: Optional prior observations to seed this invocation.
        capabilities: Registered tools available to the loop. Defaults to
            tools.TOOLS.
        model: Model ID passed to the existing call_nvidia client.
        max_decisions: Maximum number of LLM decisions in this invocation.
            Must be between 1 and MAX_ALLOWED_DECISIONS.

    Returns:
        An AgenticLoopResult describing why the loop stopped and the
        observations collected during the invocation.

    Raises:
        ValueError: If max_decisions is outside the allowed range.
    """
    if not 1 <= max_decisions <= MAX_ALLOWED_DECISIONS:
        raise ValueError(
            f"max_decisions must be between 1 and "
            f"{MAX_ALLOWED_DECISIONS}; received {max_decisions}."
        )

    available_capabilities = list(
        TOOLS if capabilities is None else capabilities
    )

    capability_map = {
        capability.name: capability
        for capability in available_capabilities
        if isinstance(getattr(capability, "name", None), str)
        and capability.name.strip()
    }

    # Bound seeded history as well as results from actions in this invocation.
    collected_observations = [
        _bound_observation(observation)
        for observation in (observations or ())
    ][-MAX_OBSERVATION_COUNT:]

    decisions_made = 0

    for _ in range(max_decisions):
        try:
            context = build_agentic_loop_context(
                state=state,
                observations=collected_observations,
                capabilities=available_capabilities,
                goal=goal,
            )

            prompt = AGENTIC_LOOP_PROMPT.format(
                **context.model_dump()
            )

            decision = await call_nvidia(
                prompt=prompt,
                model=model,
                subagent=True,
                state_model=AgenticLoopDecision,
            )

            if not isinstance(decision, AgenticLoopDecision):
                raise TypeError(
                    "The LLM client returned an unexpected decision type: "
                    f"{type(decision).__name__}."
                )

            decisions_made += 1

        except Exception as exc:
            return AgenticLoopResult(
                status=AgenticLoopStatus.FAILED,
                decisions_made=decisions_made,
                observations=collected_observations,
                error=(
                    f"Agentic-loop decision failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        if decision.action == AgenticLoopAction.FINISH:
            return AgenticLoopResult(
                status=AgenticLoopStatus.FINISHED,
                decisions_made=decisions_made,
                final_response=decision.final_response,
                rationale=decision.rationale,
                completion_evidence=decision.completion_evidence,
                observations=collected_observations,
            )

        if decision.action == AgenticLoopAction.CLARIFICATION:
            return AgenticLoopResult(
                status=AgenticLoopStatus.CLARIFICATION_REQUIRED,
                decisions_made=decisions_made,
                clarification_question=decision.clarification_question,
                rationale=decision.rationale,
                observations=collected_observations,
            )

        if decision.action == AgenticLoopAction.COMPLEX_EXECUTION:
            return AgenticLoopResult(
                status=AgenticLoopStatus.COMPLEX_EXECUTION_REQUESTED,
                decisions_made=decisions_made,
                rationale=decision.rationale,
                observations=collected_observations,
            )

        if decision.action == AgenticLoopAction.CAPABILITY:
            capability_name = decision.capability_name or ""
            capability = capability_map.get(capability_name)

            if capability is None:
                collected_observations.append(
                    _bound_observation(
                        "Capability execution was not attempted: "
                        f"{capability_name!r} is not in the registered "
                        "capability set for this invocation."
                    )
                )
                continue

            try:
                result = await capability.ainvoke(decision.arguments)

                collected_observations.append(
                    _format_capability_observation(
                        capability_name=capability_name,
                        result=result,
                    )
                )

            except Exception as exc:
                # A tool failure is evidence for the next decision, not
                # proof that the overall objective is impossible.
                collected_observations.append(
                    _bound_observation(
                        f"Capability: {capability_name}\n"
                        f"Execution error: {type(exc).__name__}: {exc}"
                    )
                )

            continue

        # AgenticLoopDecision constrains the action enum. This branch is
        # defensive against future changes to the action contract.
        return AgenticLoopResult(
            status=AgenticLoopStatus.FAILED,
            decisions_made=decisions_made,
            observations=collected_observations,
            error=f"Unsupported agentic-loop action: {decision.action!r}.",
        )

    return AgenticLoopResult(
        status=AgenticLoopStatus.BUDGET_EXHAUSTED,
        decisions_made=decisions_made,
        rationale=(
            "The agentic loop reached its decision budget before selecting "
            "FINISH, CLARIFICATION, or COMPLEX_EXECUTION."
        ),
        observations=collected_observations,
    )


def _format_capability_observation(
    *,
    capability_name: str,
    result: Any,
) -> str:
    """Format the actual capability result without semantic interpretation."""
    if isinstance(result, str):
        rendered_result = result
    else:
        try:
            rendered_result = json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except (TypeError, ValueError):
            rendered_result = str(result)

    return _bound_observation(
        f"Capability: {capability_name}\n"
        f"Returned result:\n{rendered_result}"
    )


def _bound_observation(observation: Any) -> str:
    """Convert an observation to bounded text for storage and prompt use."""
    rendered = (
        observation
        if isinstance(observation, str)
        else str(observation)
    ).strip()

    if len(rendered) <= MAX_OBSERVATION_CHARS:
        return rendered or "(empty observation)"

    available = max(
        0,
        MAX_OBSERVATION_CHARS - len(_OBSERVATION_TRUNCATION_MARKER),
    )

    return rendered[:available] + _OBSERVATION_TRUNCATION_MARKER
