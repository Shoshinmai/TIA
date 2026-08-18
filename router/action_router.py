def action_router(state):

    if state["action_type"] == "artifact_query":
        return "artifact_retriever"

    return "validator"
