from agents.terminal.state import TerminalState


def terminal_observer_node(state: TerminalState):

    print("\n[OBSERVATION]")
    print(state["compressed_observation"])

    if state.get("artifact_ids"):
        print(f"\nArtifacts: " f"{len(state['artifact_ids'])}")

    planner_output = state.get("planner_output")

    strategy = ""

    if planner_output is not None:
        strategy = planner_output.planning_step.strategy

    attempt = state.get("step_count", 0) + 1

    entry = f"""
    ==================================================
    ATTEMPT {attempt}
    ==================================================

    Strategy:
    {strategy}

    Outcome:
    {state.get("compressed_observation", "")}

    Conclusion:
    {state.get("observation_conclusion", "")}
    """
    updated_scratchpad = state.get("scratchpad", "") + "\n" + entry
    return {
        "scratchpad": updated_scratchpad,
        "step_count": state.get("step_count", 0) + 1,
    }
