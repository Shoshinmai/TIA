from agents.terminal.models import (
    ActiveTaskMemory,
    ArtifactReference,
    ExecutionMemory,
    ThreadMemory,
)
from agents.terminal.task_plan.models import TaskPlan


def format_runtime_memory(
    active_memory: ActiveTaskMemory,
    execution_memory: ExecutionMemory,
    thread_memory: ThreadMemory,
) -> str:
    """
    Convert runtime memory into a planner-friendly text block.
    """

    sections: list[str] = []

    # -----------------------------------------
    # Known Facts
    # -----------------------------------------

    if active_memory.known_facts:
        sections.append("## Known Facts")

        for fact in active_memory.known_facts:
            sections.append(f"- {fact.statement}")

    # -----------------------------------------
    # Resources
    # -----------------------------------------

    if active_memory.discovered_resources:
        sections.append("")
        sections.append("## Discovered Resources")

        for resource in active_memory.discovered_resources:
            sections.append(f"- [{resource.type.value}] {resource.identifier}")

    # -----------------------------------------
    # Completed Work
    # -----------------------------------------

    if active_memory.completed_work:
        sections.append("")
        sections.append("## Completed Work")

        for item in active_memory.completed_work:
            sections.append(f"- {item}")

    # -----------------------------------------
    # Pending Work
    # -----------------------------------------

    if active_memory.unresolved_needs:
        sections.append("")
        sections.append("## Pending Work")

        for item in active_memory.unresolved_needs:
            sections.append(f"- {item}")

    # -----------------------------------------
    # Execution Summary
    # -----------------------------------------

    if execution_memory.tool_history:
        sections.append("")
        sections.append("## Tool History")

        for tool in execution_memory.tool_history[-5:]:
            sections.append(f"- {tool}")

    # -----------------------------------------
    # Thread Summary
    # -----------------------------------------

    if thread_memory.summary:
        sections.append("")
        sections.append("## Thread Summary")
        sections.append(thread_memory.summary)

    if not sections:
        return "No runtime memory available."

    return "\n".join(sections)


def format_active_memory(active_memory: ActiveTaskMemory) -> str:
    sections: list[str] = []

    # -----------------------------------------
    # Known Facts
    # -----------------------------------------

    if active_memory.known_facts:
        sections.append("## Known Facts")

        for fact in active_memory.known_facts:
            sections.append(f"- {fact.statement}")

    # -----------------------------------------
    # Resources
    # -----------------------------------------

    if active_memory.discovered_resources:
        sections.append("")
        sections.append("## Discovered Resources")

        for resource in active_memory.discovered_resources:
            sections.append(f"- [{resource.type.value}] {resource.identifier}")

    # -----------------------------------------
    # Completed Work
    # -----------------------------------------

    if active_memory.completed_work:
        sections.append("")
        sections.append("## Completed Work")

        for item in active_memory.completed_work:
            sections.append(f"- {item}")

    # -----------------------------------------
    # Pending Work
    # -----------------------------------------

    if active_memory.unresolved_needs:
        sections.append("")
        sections.append("## Pending Work")

        for item in active_memory.unresolved_needs:
            sections.append(f"- {item}")

    if not sections:
        return "No runtime memory available."

    return "\n".join(sections)


def format_task_plan(
    task_plan: TaskPlan,
) -> str:
    """
    Convert the current Task Plan into planner-facing text.
    """

    sections: list[str] = []

    sections.append(f"Goal: {task_plan.goal}")
    sections.append(f"Status: {task_plan.status.value}")
    sections.append("")
    sections.append("Tasks:")

    for task in task_plan.tasks:
        sections.append(f"- [{task.status.value}] {task.objective}")

        if task.dependencies:
            sections.append(f"  depends on: {', '.join(task.dependencies)}")

    return "\n".join(sections)


def format_execution_summary(
    execution_memory: ExecutionMemory,
) -> str:

    if not execution_memory.attempts:
        return "No execution history available."

    sections: list[str] = []

    for attempt in execution_memory.attempts[-5:]:

        sections.append(
            "\n".join(
                [
                    f"Attempt {attempt.step}",
                    f"- Capability: {attempt.capability}",
                    f"- Strategy: {attempt.strategy}",
                    f"- Status: {attempt.status.value}",
                    f"- Progress made: {attempt.progress_made}",
                    f"- Outcome: {attempt.outcome or 'None'}",
                    f"- Error: {attempt.error or 'None'}",
                    (
                        f"- Artifacts: "
                        f"{', '.join(attempt.artifact_ids)}"
                        if attempt.artifact_ids
                        else "- Artifacts: None"
                    ),
                ]
            )
        )

    return "\n\n".join(sections)

def format_artifact_catalog(
    artifact_references: list[ArtifactReference],
) -> str:
    """
    Format available artifact metadata for LLM consumption.
    """

    if not artifact_references:
        return "No artifacts available."

    sections: list[str] = []

    for artifact in artifact_references:

        sections.append(
            "\n".join(
                [
                    f"Artifact ID: {artifact.artifact_id}",
                    f"Type: {artifact.artifact_type}",
                    f"Source: {artifact.source}",
                    f"Scope: {artifact.scope.value}",
                    f"Summary: {artifact.summary or 'No summary.'}",
                ]
            )
        )

    return "\n\n".join(sections)