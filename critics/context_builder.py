from __future__ import annotations

from typing import Any

from critics.models import CriticContext
from runtime.events import RuntimeEvent
from runtime.plan_execution_outcome import (
    PlanExecutionOutcome,
)
from state import TerminalState
from task_plan.manager import TaskPlanManager
from task_plan.models import TaskPlan
from utils.memory_formatter import (
    format_active_memory,
    format_artifact_catalog,
    format_execution_summary,
    format_task_plan,
)


def build_critic_context(
    state: dict[str, Any] | TerminalState,
) -> CriticContext:
    """
    Build the complete context supplied to the Critic.

    The Critic receives a relevant, formatted view of the current
    execution situation rather than the raw runtime state.

    The builder supports both:

    1. The existing single-task runtime path.
    2. The concurrent plan-level execution path.

    This function does not:
        - perform Critic reasoning,
        - modify the TaskPlan,
        - modify the ExecutionWorkflow,
        - execute tools,
        - perform runtime routing.
    """

    task_plan = state.get(
        "task_plan",
    )

    if task_plan is None:
        raise ValueError(
            "Cannot build CriticContext without a TaskPlan."
        )

    plan_execution_outcome = state.get(
        "plan_execution_outcome",
    )

    runtime_state = state.get(
        "runtime_state",
    )

    # ==========================================================
    # Shared context
    # ==========================================================

    overall_goal = task_plan.goal

    task_plan_summary = format_task_plan(
        task_plan,
    )

    execution_summary = _build_execution_summary(
        state,
    )

    active_memory = format_active_memory(
        active_memory=state["active_memory"],
    )

    artifact_catalog = format_artifact_catalog(
        state.get(
            "artifact_references",
            [],
        ),
    )

    # ==========================================================
    # FINAL PLAN EXHAUSTION REVIEW
    # ==========================================================
    #
    # IMPORTANT:
    #
    # This check MUST happen before the generic concurrent
    # PlanExecutionOutcome branch.
    #
    # PLAN_EXHAUSTED means:
    #
    #     every planned TaskPlan task has reached a terminal
    #     completed state.
    #
    # It does NOT mean:
    #
    #     the user's overall goal has been achieved.
    #
    # The Critic must perform the semantic final-goal review.
    # ==========================================================

    is_plan_exhausted_review = (
        runtime_state is not None
        and runtime_state.last_event
        == RuntimeEvent.PLAN_EXHAUSTED
    )

    if is_plan_exhausted_review:

        return CriticContext(
            overall_goal=overall_goal,

            task_plan_summary=task_plan_summary,

            plan_execution_outcome=(
                "PLAN_EXHAUSTED: every task currently contained "
                "in the rolling TaskPlan has reached COMPLETED. "
                "This is a deterministic TaskPlan state only. "
                "It does NOT establish that the user's overall "
                "goal has been achieved."
            ),

            current_objective=(
                "The rolling TaskPlan has been exhausted. "
                "Perform the final semantic evaluation of the "
                "overall user goal using the original goal, "
                "execution evidence, Active Task Memory, and "
                "artifacts. Determine whether every material "
                "requirement of the user's goal has actually "
                "been satisfied."
            ),

            remaining_objectives=(
                "No unfinished TaskPlan objectives remain.\n\n"
                "The absence of unfinished TaskPlan objectives "
                "does not itself prove that the user's overall "
                "goal is complete. Independently verify the "
                "goal against concrete execution evidence."
            ),

            execution_summary=execution_summary,

            active_memory=active_memory,

            artifact_catalog=artifact_catalog,
        )

    # ==========================================================
    # CONCURRENT PLAN-LEVEL REVIEW
    # ==========================================================
    #
    # This represents an ordinary concurrent wave boundary.
    #
    # The wave has completed, but the TaskPlan may still contain
    # READY or otherwise unfinished work.
    # ==========================================================

    if plan_execution_outcome is not None:

        return _build_concurrent_critic_context(
            task_plan=task_plan,
            outcome=plan_execution_outcome,
            execution_summary=execution_summary,
            active_memory=active_memory,
            artifact_catalog=artifact_catalog,
            task_plan_summary=task_plan_summary,
        )

    # ==========================================================
    # Existing single-task review path
    # ==========================================================

    current_task = TaskPlanManager.get_in_progress_task(
        plan=task_plan,
    )

    if current_task is None:
        raise ValueError(
            "Cannot build CriticContext because the TaskPlan "
            "has no IN_PROGRESS task."
        )

    return CriticContext(
        overall_goal=overall_goal,

        task_plan_summary=task_plan_summary,

        plan_execution_outcome=(
            "The runtime is reviewing the current task "
            "using the existing single-task execution path."
        ),

        current_objective=current_task.objective,

        remaining_objectives=_build_remaining_objectives(
            task_plan=task_plan,
            current_task_id=current_task.task_id,
        ),

        execution_summary=execution_summary,

        active_memory=active_memory,

        artifact_catalog=artifact_catalog,
    )


def _build_concurrent_critic_context(
    *,
    task_plan: TaskPlan,
    outcome: PlanExecutionOutcome,
    execution_summary: str,
    active_memory: str,
    artifact_catalog: str,
    task_plan_summary: str,
) -> CriticContext:
    """
    Build CriticContext for a completed concurrent execution
    boundary.

    The Critic receives the whole plan-level situation rather than
    a singular current task.

    Importantly, task execution evidence is formatted explicitly
    from RuntimeProcessingResult instead of exposing raw Python
    representations.
    """

    return CriticContext(
        overall_goal=task_plan.goal,

        task_plan_summary=task_plan_summary,

        plan_execution_outcome=(
            _format_plan_execution_outcome(
                outcome,
            )
        ),

        current_objective=(
            _build_concurrent_execution_situation(
                outcome,
            )
        ),

        remaining_objectives=(
            _build_remaining_objectives_for_plan(
                task_plan,
            )
        ),

        execution_summary=execution_summary,

        active_memory=active_memory,

        artifact_catalog=artifact_catalog,
    )


def _build_concurrent_execution_situation(
    outcome: PlanExecutionOutcome,
) -> str:
    """
    Describe the stable concurrent execution boundary without
    implying semantic goal completion.
    """

    condition = outcome.condition.value

    if outcome.failed_task_ids:
        return (
            "Concurrent execution reached a stable boundary "
            f"with condition '{condition}'. "
            "One or more tasks failed. Determine whether those "
            "failures affect the user's overall goal and whether "
            "recovery is required."
        )

    if outcome.blocked_task_ids:
        return (
            "Concurrent execution reached a stable boundary "
            f"with condition '{condition}'. "
            "One or more tasks are blocked by dependency state."
        )

    if outcome.cancelled_task_ids:
        return (
            "Concurrent execution reached a stable boundary "
            f"with condition '{condition}'. "
            "One or more tasks were cancelled."
        )

    if condition == "completed":
        return (
            "The current rolling TaskPlan has been fully executed. "
            "This proves only that the planned tasks reached their "
            "terminal states. It does NOT prove that the overall "
            "user goal has been achieved. The Critic must independently "
            "verify every material goal requirement using concrete "
            "execution evidence, Active Task Memory, and artifacts."
        )

    return (
        "Concurrent execution reached a stable plan-level "
        f"boundary with condition '{condition}'."
    )


def _format_plan_execution_outcome(
    outcome: PlanExecutionOutcome,
) -> str:
    """
    Format the structured concurrent execution outcome for the
    Critic prompt.

    This function deliberately exposes the semantic evidence
    produced by the Runtime Processing Pipeline.

    It does not perform semantic interpretation or decide whether
    the user goal is complete.
    """

    lines = [
        f"Condition: {outcome.condition.value}",
        "",
        "Completed Tasks:",
    ]

    if outcome.completed_task_ids:
        lines.extend(
            f"- {task_id}"
            for task_id in outcome.completed_task_ids
        )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "Failed Tasks:",
        ]
    )

    if outcome.failed_task_ids:
        lines.extend(
            f"- {task_id}"
            for task_id in outcome.failed_task_ids
        )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "Blocked Tasks:",
        ]
    )

    if outcome.blocked_task_ids:
        lines.extend(
            f"- {task_id}"
            for task_id in outcome.blocked_task_ids
        )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "Cancelled Tasks:",
        ]
    )

    if outcome.cancelled_task_ids:
        lines.extend(
            f"- {task_id}"
            for task_id in outcome.cancelled_task_ids
        )
    else:
        lines.append("- None")

    # ==========================================================
    # Task-level execution evidence
    # ==========================================================

    if outcome.task_results:

        lines.extend(
            [
                "",
                "Task Execution Evidence:",
            ]
        )

        for task_id, result in outcome.task_results.items():

            lines.append(
                f"- Task: {task_id}"
            )

            lines.append(
                f"  Task status: {result.status.value}"
            )

            if result.error:
                lines.append(
                    f"  Worker error: {result.error}"
                )

            # --------------------------------------------------
            # RuntimeProcessingResult evidence
            # --------------------------------------------------

            processing_results = (
                result.processing_results
            )

            if processing_results:

                lines.append(
                    "  Processing results:"
                )

                for index, processed in enumerate(
                    processing_results,
                    start=1,
                ):

                    normalized = (
                        processed.normalized_result
                    )

                    execution = (
                        normalized.execution
                    )

                    lines.append(
                        f"    [{index}] Tool: "
                        f"{normalized.context.tool_name}"
                    )

                    lines.append(
                        "        Execution success: "
                        f"{execution.success}"
                    )

                    lines.append(
                        "        Progress made: "
                        f"{execution.progress_made}"
                    )

                    if execution.return_code is not None:
                        lines.append(
                            "        Return code: "
                            f"{execution.return_code}"
                        )

                    if execution.message:
                        lines.append(
                            "        Message: "
                            f"{execution.message}"
                        )

                    if execution.stdout:
                        lines.append(
                            "        stdout:"
                        )

                        lines.append(
                            _indent_text(
                                execution.stdout,
                                indent="          ",
                            )
                        )

                    if execution.stderr:
                        lines.append(
                            "        stderr:"
                        )

                        lines.append(
                            _indent_text(
                                execution.stderr,
                                indent="          ",
                            )
                        )

                    # ------------------------------------------
                    # Structured facts
                    # ------------------------------------------

                    if normalized.facts:

                        lines.append(
                            "        Facts:"
                        )

                        for fact in normalized.facts:

                            lines.append(
                                "          - "
                                f"{fact.statement}"
                            )

                    # ------------------------------------------
                    # Discovered resources
                    # ------------------------------------------

                    if normalized.resources:

                        lines.append(
                            "        Resources:"
                        )

                        for resource in (
                            normalized.resources
                        ):

                            lines.append(
                                "          - "
                                f"{resource.type.value}: "
                                f"{resource.identifier}"
                            )

                    # ------------------------------------------
                    # Artifact decision
                    # ------------------------------------------

                    artifact_decision = (
                        processed.artifact_decision
                    )

                    lines.append(
                        "        Artifact action: "
                        f"{artifact_decision.action.value}"
                    )

                    lines.append(
                        "        Artifact reason: "
                        f"{artifact_decision.reason}"
                    )

                    if artifact_decision.artifact:

                        lines.append(
                            "        Artifact candidate: "
                            f"{artifact_decision.artifact.summary}"
                        )

                    # ------------------------------------------
                    # Memory update proposal
                    # ------------------------------------------

                    memory_update = (
                        processed.memory_update
                    )

                    if memory_update.known_facts:

                        lines.append(
                            "        Memory known facts:"
                        )

                        for fact in (
                            memory_update.known_facts
                        ):

                            lines.append(
                                "          - "
                                f"{fact.statement}"
                            )

                    if memory_update.discovered_resources:

                        lines.append(
                            "        Memory resources:"
                        )

                        for resource in (
                            memory_update.discovered_resources
                        ):

                            lines.append(
                                "          - "
                                f"{resource.type.value}: "
                                f"{resource.identifier}"
                            )

                    if memory_update.completed_work:

                        lines.append(
                            "        Completed work:"
                        )

                        for work in (
                            memory_update.completed_work
                        ):

                            lines.append(
                                f"          - {work}"
                            )

                    if memory_update.unresolved_needs:

                        lines.append(
                            "        Unresolved needs:"
                        )

                        for need in (
                            memory_update.unresolved_needs
                        ):

                            lines.append(
                                f"          - {need}"
                            )

                    if memory_update.evidence:

                        lines.append(
                            "        Evidence:"
                        )

                        for evidence in (
                            memory_update.evidence
                        ):

                            lines.append(
                                f"          - {evidence}"
                            )

            else:

                # --------------------------------------------------
                # Fallback when a task completed without a
                # RuntimeProcessingResult.
                #
                # This is intentionally explicit so the Critic
                # knows that execution status alone is not evidence
                # of goal completion.
                # --------------------------------------------------

                lines.append(
                    "  Processing results: None"
                )

            # --------------------------------------------------
            # Legacy/general result payload
            # --------------------------------------------------

            if result.result is not None:

                result_payload = result.result

                if isinstance(
                    result_payload,
                    dict,
                ):

                    # Do not duplicate the full processing results
                    # because they were already rendered above.
                    #
                    # Only expose additional fields.
                    additional_payload = {
                        key: value
                        for key, value
                        in result_payload.items()
                        if key
                        not in {
                            "processing_results",
                        }
                    }

                    if additional_payload:

                        lines.append(
                            "  Additional worker result:"
                        )

                        lines.append(
                            _indent_text(
                                str(
                                    additional_payload
                                ),
                                indent="    ",
                            )
                        )

                else:

                    lines.append(
                        "  Worker result:"
                    )

                    lines.append(
                        _indent_text(
                            str(result_payload),
                            indent="    ",
                        )
                    )

    else:

        lines.extend(
            [
                "",
                "Task Execution Evidence:",
                "- None",
            ]
        )

    return "\n".join(lines)


def _indent_text(
    value: str,
    *,
    indent: str,
) -> str:
    """
    Indent multiline execution output while preserving its
    contents.
    """

    text = str(value)

    return "\n".join(
        indent + line
        for line in text.splitlines()
    )


def _build_remaining_objectives_for_plan(
    task_plan: TaskPlan,
) -> str:
    """
    Build a Critic-facing description of what remains.

    When the plan is exhausted, explicitly state that plan exhaustion
    is not equivalent to goal completion.
    """

    remaining_tasks = [
        task
        for task in task_plan.tasks
        if task.status.value
        not in {
            "completed",
            "cancelled",
        }
    ]

    if remaining_tasks:

        lines = [
            "Unfinished TaskPlan objectives:"
        ]

        for index, task in enumerate(
            remaining_tasks,
            start=1,
        ):

            lines.append(
                f"{index}. "
                f"[{task.status.value}] "
                f"{task.objective}"
            )

            if task.dependencies:
                lines.append(
                    "   depends on: "
                    + ", ".join(task.dependencies)
                )

        return "\n".join(lines)

    return (
        "No unfinished TaskPlan objectives remain.\n\n"
        "IMPORTANT: The rolling TaskPlan is exhausted, but the "
        "overall user goal is NOT automatically considered complete. "
        "The Critic must still prove that every material goal "
        "requirement has been satisfied."
    )


def _build_remaining_objectives(
    *,
    task_plan: Any | TaskPlan,
    current_task_id: str,
) -> str:
    """
    Build a compact Critic-facing representation of the
    objectives that remain in the TaskPlan.

    Preserved for the existing single-task execution path.
    """

    remaining_tasks = [
        task
        for task in task_plan.tasks
        if (
            task.task_id != current_task_id
            and task.status.value
            not in {
                "completed",
                "cancelled",
            }
        )
    ]

    if not remaining_tasks:
        return "No remaining objectives."

    lines = []

    for index, task in enumerate(
        remaining_tasks,
        start=1,
    ):
        lines.append(
            f"{index}. {task.objective}"
        )

    return "\n".join(lines)


def _build_execution_summary(
    state: dict[str, Any] | TerminalState,
) -> str:
    """
    Build the Critic-facing execution summary.

    Existing execution memory remains the primary source of
    execution history.

    The current ExecutionWorkflow is appended only when the
    legacy single-workflow path is active.
    """

    summary = format_execution_summary(
        state["execution_memory"],
    )

    workflow = state.get(
        "execution_workflow",
    )

    if workflow is None:
        return summary

    workflow_lines = [
        "",
        "CURRENT EXECUTION WORKFLOW",
        "---------------------------",
        f"Workflow ID: {workflow.workflow_id}",
        f"Workflow Objective: {workflow.objective}",
        f"Workflow Strategy: {workflow.execution_strategy}",
        f"Workflow Status: {workflow.status.value}",
    ]

    if workflow.steps:

        workflow_lines.append("")
        workflow_lines.append(
            "Workflow Steps:"
        )

        for index, step in enumerate(
            workflow.steps,
            start=1,
        ):

            workflow_lines.append(
                f"{index}. {step.description}"
            )

            workflow_lines.append(
                f"   Capability: {step.capability}"
            )

            workflow_lines.append(
                f"   Status: {step.status.value}"
            )

    return (
        summary
        + "\n"
        + "\n".join(workflow_lines)
    )