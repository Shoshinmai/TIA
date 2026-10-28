from __future__ import annotations

import asyncio
import json
import os
import uuid

from dotenv import load_dotenv

from state import TerminalState

load_dotenv()

from runtime_graph import runtime_graph


async def main() -> None:
    print("=== TIA: Isolated Agentic Loop ===")
    print("Enter a goal for the agent to work on.")

    # goal = input("\nGoal: ").strip()
    # if not goal:
    #     print("Error: goal cannot be empty.")
    #     return

    # The initializer requires a LangGraph thread_id.
    thread_id = f"agentic-loop-{uuid.uuid4().hex[:12]}"

    initial_state = {
        "goal": """list the installed games on the steam app. take the critic help is necessary.""",
        # "goal": """Inspect the current project directory,identify the main application entry point,
        #            and explain what it does. Use the available capabilities to gather evidence before responding.""",
        "workspace": os.getcwd(),
        "messages": [],
    }

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    print("\nRunning agentic loop...\n")

    try:
        final_state = await runtime_graph.ainvoke(
            initial_state,  # pyright: ignore[reportArgumentType]
            config=config,  # pyright: ignore[reportArgumentType]
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return
    except Exception as exc:
        print(f"\nAgent execution failed: {type(exc).__name__}: {exc}")
        raise

    result = final_state.get("agentic_loop_result")
    output = final_state.get("agent_output")

    print("\n" + "=" * 60)
    print("AGENT OUTPUT")
    print("=" * 60)

    if output is not None:
        print(output.message)
        print(f"\nOutput type: {output.output_type.value}")
    else:
        print("The graph returned without producing an AgentOutput.")

    if result is not None:
        print("\n" + "-" * 60)
        print("LOOP SUMMARY")
        print("-" * 60)
        print(f"Status: {result.status.value}")
        print(f"Decisions made: {result.decisions_made}")
        print(f"Critic responses: {result.critic_responses_received}")

        if result.rationale:
            print(f"Rationale: {result.rationale}")

        if result.error:
            print(f"Error: {result.error}")

        if result.observations:
            print("\nObservations:")
            for index, observation in enumerate(result.observations, 1):
                print(f"\n[{index}] {observation}")

        print("\nStructured result:")
        print(
            json.dumps(
                result.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            )
        )

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
