from __future__ import annotations

import json

from llm.llmclient import call_nvidia
from output.models import (
    AgentOutput,
    OutputContext,
)


OUTPUT_GENERATION_PROMPT = """
You are TIA's user-facing output generator.

Your responsibility is to communicate the result of the agent's
work to the user.

You receive a bounded OutputContext produced from authoritative
runtime state.

IMPORTANT RULES:

1. OUTPUT TYPE IS AUTHORITATIVE.
   Never change the supplied output type.

2. USE ONLY SUPPORTED INFORMATION.
   Every factual claim must be supported by the OutputContext.

3. NEVER INVENT:
   - facts
   - execution results
   - files
   - paths
   - commands
   - timings
   - capabilities
   - artifacts
   - successful outcomes

4. DO NOT REASON ABOUT WHETHER THE GOAL IS COMPLETE.
   That decision has already been made by the runtime/Critic.

5. DO NOT MODIFY AGENT STATE.
   You only generate communication.

6. DO NOT EXPOSE INTERNAL IMPLEMENTATION DETAILS unless
   necessary to explain the user's outcome.

7. DO NOT mention:
   - Planner
   - Critic
   - RuntimeKernel
   - RuntimeState
   - TaskPlan internals
   - internal Python classes
   unless the user explicitly asked about internals.

8. ANSWER THE ORIGINAL USER GOAL DIRECTLY.

9. FINAL:
   Explain what was accomplished and the concrete result.

10. BLOCKED:
   Explain what prevents completion and, when the evidence supports it,
   what information or action is needed next.

11. FAILED:
   Explain that the requested work could not be completed and give the
   relevant supported reason.

12. CANCELLED:
   Explain that execution was cancelled.

13. If evidence is insufficient for a claim, explicitly state that the
   result could not be established.

14. Do not produce labels such as:
   "Output:"
   "Final Answer:"
   "Response:"

15. Return only the user-facing message.

OUTPUT CONTEXT:
{context}
"""


class OutputGenerator:
    """
    Generate user-facing communication from a bounded OutputContext.
    """

    async def generate(
        self,
        context: OutputContext,
    ) -> AgentOutput:

        serialized_context = json.dumps(
            context.model_dump(
                mode="json",
            ),
            ensure_ascii=False,
            indent=2,
        )

        prompt = OUTPUT_GENERATION_PROMPT.format(
            context=serialized_context,
        )

        message = await call_nvidia(
            prompt,
            "nvidia/nemotron-3.5-lightning-30b-a3b",
        )

        if not isinstance(
            message,
            str,
        ):
            message = str(
                message
            )

        message = message.strip()

        if not message:
            raise ValueError(
                "Output generator returned an empty message."
            )

        return AgentOutput(
            output_type=context.output_type,
            message=message,
            termination_reason=context.termination_reason,
        )


__all__ = [
    "OutputGenerator",
]