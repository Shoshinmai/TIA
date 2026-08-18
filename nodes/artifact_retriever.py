from agents.terminal.memory.retriever import ArtifactRetriever

from agents.terminal.state import TerminalState


def artifact_retriever_node(state: TerminalState):

    query = state["command"]

    artifact_ids = state.get("artifact_ids", [])

    if not artifact_ids:

        return {"compressed_observation": "No artifacts available."}

    artifact_id = artifact_ids[-1]

    if query.startswith("find_file:"):

        filename = query.replace("find_file:", "").strip()

    matches = ArtifactRetriever.find_file(artifact_id, filename)

    if not matches:

        observation = f"No files found " f"matching {filename}"

    else:

        observation = "\n".join(matches[:20])

    print("\n[ARTIFACT RETRIEVER]")

    print(f"Matches: " f"{len(matches)}")

    return {"compressed_observation": observation, "success": True, "error": ""}
