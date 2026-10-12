from __future__ import annotations

from typing import Any

from models import AttemptStatus
from output.models import (
    OutputArtifact,
    OutputContext,
    OutputDecision,
    OutputExecutionSummary,
    OutputKnowledge,
    OutputOutcome,
    OutputTaskSummary,
    OutputType,
)
from runtime.events import RuntimeEvent
from runtime.kernel import RuntimeKernel
from runtime.modes import RuntimeMode
from runtime.models import RuntimeDecisionContext
from runtime.plan_execution_outcome import (
    PlanExecutionCondition,
    PlanExecutionOutcome,
)
from state import TerminalState


_MAX_FACTS = 40
_MAX_COMPLETED_WORK = 40
_MAX_RESOURCES = 40
_MAX_UNRESOLVED_NEEDS = 20
_MAX_TASKS = 50
_MAX_ERRORS = 20
_MAX_RESULTS = 30
_MAX_ARTIFACTS = 30

_MAX_TEXT_LENGTH = 1000
_MAX_ERROR_LENGTH = 500


class OutputContextBuilder:
    """
    Deterministically project authoritative TerminalState into a
    bounded OutputContext.

    This builder:
        - performs no LLM reasoning,
        - performs no state mutation,
        - executes no tools,
        - retrieves no artifact contents.
    """

    @classmethod
    def build(
        cls,
        state: TerminalState,
    ) -> OutputContext:

        runtime_state = state.get("runtime_state")
        termination_reason = (
            runtime_state.metadata.get("termination_reason")
            if runtime_state is not None
            else None
        )

        return OutputContext(
            goal=cls._build_goal(
                state,
            ),
            output_type=cls._resolve_output_type(
                state,
            ),
            outcome=cls._build_outcome(
                state,
            ),
            tasks=cls._build_tasks(
                state,
            ),
            knowledge=cls._build_knowledge(
                state,
            ),
            execution=cls._build_execution(
                state,
            ),
            artifacts=cls._build_artifacts(
                state,
            ),
            decision=cls._build_decision(
                runtime_state.decision_context
                if runtime_state is not None
                else None
            ),
            termination_reason=termination_reason,
        )

    # ==========================================================
    # Goal
    # ==========================================================

    @staticmethod
    def _build_goal(
        state: TerminalState,
    ) -> str:

        task = state.get(
            "task",
        )

        if task is not None and task.goal:
            return task.goal

        task_plan = state.get(
            "task_plan",
        )

        if task_plan is not None:
            return task_plan.goal

        raise ValueError(
            "Cannot build OutputContext without a task goal."
        )

    # ==========================================================
    # Output Type
    # ==========================================================

    @classmethod
    def _resolve_output_type(
        cls,
        state: TerminalState,
    ) -> OutputType:

        runtime_state = state.get(
            "runtime_state",
        )

        last_event = (
            runtime_state.last_event
            if runtime_state is not None
            else None
        )

        mode = (
            runtime_state.mode
            if runtime_state is not None
            else None
        )

        # ------------------------------------------------------
        # Goal completion is authoritative.
        # ------------------------------------------------------

        if last_event == RuntimeEvent.GOAL_COMPLETED:
            return OutputType.FINAL

        # ------------------------------------------------------
        # Cancellation.
        # ------------------------------------------------------

        if last_event in (
            RuntimeEvent.PLAN_CANCELLED,
            RuntimeEvent.TASK_CANCELLED,
        ):
            return OutputType.CANCELLED

        # ------------------------------------------------------
        # Runtime failure.
        # ------------------------------------------------------

        if mode == RuntimeMode.ERROR:
            return OutputType.FAILED

        # ------------------------------------------------------
        # Budget exhaustion / partial completion.
        # ------------------------------------------------------

        if runtime_state is not None:
            termination_reason = runtime_state.metadata.get("termination_reason")
            if termination_reason in (
                RuntimeKernel.TERMINAL_REASON_BUDGET_EXHAUSTED,
                RuntimeKernel.TERMINAL_REASON_GOAL_COMPLETION_REJECTED,
                RuntimeKernel.TERMINAL_REASON_PARTIAL_COMPLETION,
            ):
                return OutputType.PARTIAL_COMPLETION

        # ------------------------------------------------------
        # Stable execution outcome.
        # ------------------------------------------------------

        outcome = state.get(
            "plan_execution_outcome",
        )

        if outcome is not None:

            if outcome.condition == PlanExecutionCondition.BLOCKED:
                return OutputType.BLOCKED

            if outcome.condition == PlanExecutionCondition.CANCELLED:
                return OutputType.CANCELLED

            if outcome.condition == PlanExecutionCondition.FAILED:
                return OutputType.FAILED

        # ------------------------------------------------------
        # Terminal event fallback when no plan outcome exists.
        # ------------------------------------------------------

        if last_event in (
            RuntimeEvent.PLAN_FAILED,
            RuntimeEvent.EXECUTION_FAILED,
            RuntimeEvent.TASK_FAILED,
        ):
            return OutputType.FAILED

        if last_event == RuntimeEvent.TASK_BLOCKED:
            return OutputType.BLOCKED

        raise ValueError(
            "Output is not available for the current runtime state. "
            "Expected a terminal completion, failure, block, or cancellation."
        )

    # ==========================================================
    # Outcome
    # ==========================================================

    @classmethod
    def _build_outcome(
        cls,
        state: TerminalState,
    ) -> OutputOutcome:

        outcome = state.get(
            "plan_execution_outcome",
        )

        if outcome is not None:
            return OutputOutcome(
                condition=outcome.condition,
                completed_task_ids=list(
                    outcome.completed_task_ids,
                ),
                failed_task_ids=list(
                    outcome.failed_task_ids,
                ),
                blocked_task_ids=list(
                    outcome.blocked_task_ids,
                ),
                cancelled_task_ids=list(
                    outcome.cancelled_task_ids,
                ),
            )

        return OutputOutcome(
            condition=cls._condition_from_terminal_event(
                state,
            ),
        )

    @staticmethod
    def _condition_from_terminal_event(
        state: TerminalState,
    ) -> PlanExecutionCondition:

        runtime_state = state.get(
            "runtime_state",
        )

        event = (
            runtime_state.last_event
            if runtime_state is not None
            else None
        )

        mapping = {
            RuntimeEvent.GOAL_COMPLETED: (
                PlanExecutionCondition.COMPLETED
            ),
            RuntimeEvent.PLAN_CANCELLED: (
                PlanExecutionCondition.CANCELLED
            ),
            RuntimeEvent.TASK_CANCELLED: (
                PlanExecutionCondition.CANCELLED
            ),
            RuntimeEvent.TASK_BLOCKED: (
                PlanExecutionCondition.BLOCKED
            ),
            RuntimeEvent.PLAN_FAILED: (
                PlanExecutionCondition.FAILED
            ),
            RuntimeEvent.EXECUTION_FAILED: (
                PlanExecutionCondition.FAILED
            ),
            RuntimeEvent.TASK_FAILED: (
                PlanExecutionCondition.FAILED
            ),
        }

        if event is None or event not in mapping:
            raise ValueError(
                "Cannot derive OutputOutcome because no "
                "PlanExecutionOutcome exists and the "
                "runtime event is not terminal."
            )

        return mapping[event]

    # ==========================================================
    # Tasks
    # ==========================================================

    @classmethod
    def _build_tasks(
        cls,
        state: TerminalState,
    ) -> list[OutputTaskSummary]:

        task_plan = state.get(
            "task_plan",
        )

        if task_plan is None:
            return []

        return [
            OutputTaskSummary(
                task_id=task.task_id,
                objective=cls._bound_text(
                    task.objective,
                ),
                status=task.status.value,
                blockers=[
                    cls._bound_text(
                        blocker,
                        _MAX_ERROR_LENGTH,
                    )
                    for blocker in task.blockers[
                        :_MAX_ERRORS
                    ]
                ],
            )
            for task in task_plan.tasks[
                :_MAX_TASKS
            ]
        ]

    # ==========================================================
    # Knowledge
    # ==========================================================

    @classmethod
    def _build_knowledge(
        cls,
        state: TerminalState,
    ) -> OutputKnowledge:

        active_memory = state.get(
            "active_memory",
        )

        if active_memory is None:
            return OutputKnowledge()

        return OutputKnowledge(
            known_facts=[
                cls._bound_text(
                    fact.statement,
                )
                for fact in active_memory.known_facts[
                    -_MAX_FACTS:
                ]
            ],
            completed_work=[
                cls._bound_text(
                    item,
                )
                for item in active_memory.completed_work[
                    -_MAX_COMPLETED_WORK:
                ]
            ],
            discovered_resources=[
                cls._bound_text(
                    f"{resource.type.value}: "
                    f"{resource.identifier}",
                )
                for resource in active_memory.discovered_resources[
                    -_MAX_RESOURCES:
                ]
            ],
            unresolved_needs=[
                cls._bound_text(
                    item,
                )
                for item in active_memory.unresolved_needs[
                    -_MAX_UNRESOLVED_NEEDS:
                ]
            ],
        )

    # ==========================================================
    # Execution
    # ==========================================================

    @classmethod
    def _build_execution(
        cls,
        state: TerminalState,
    ) -> OutputExecutionSummary:

        execution_memory = state.get(
            "execution_memory",
        )

        attempts = (
            execution_memory.attempts
            if execution_memory is not None
            else []
        )

        successful_attempts = sum(
            1
            for attempt in attempts
            if attempt.status == AttemptStatus.SUCCEEDED
        )

        failed_attempts = sum(
            1
            for attempt in attempts
            if attempt.status == AttemptStatus.FAILED
        )

        important_errors = [
            cls._bound_text(
                attempt.error,
                _MAX_ERROR_LENGTH,
            )
            for attempt in attempts
            if attempt.error
        ][-_MAX_ERRORS:]

        important_results = cls._build_result_evidence(
            state,
        )

        return OutputExecutionSummary(
            total_attempts=len(
                attempts
            ),
            successful_attempts=successful_attempts,
            failed_attempts=failed_attempts,
            important_errors=important_errors,
            important_results=important_results,
        )

    # ==========================================================
    # Task Execution Evidence
    # ==========================================================

    @classmethod
    def _build_result_evidence(
        cls,
        state: TerminalState,
    ) -> list[str]:

        outcome = state.get(
            "plan_execution_outcome",
        )

        if outcome is None:
            return []

        evidence: list[str] = []

        for task_id, task_result in outcome.task_results.items():

            if task_result.error:

                evidence.append(
                    cls._bound_text(
                        f"Task {task_id} failed: "
                        f"{task_result.error}",
                        _MAX_ERROR_LENGTH,
                    )
                )

            for processed in task_result.processing_results:

                normalized = processed.normalized_result

                execution = normalized.execution

                for fact in normalized.facts:

                    evidence.append(
                        cls._bound_text(
                            f"Task {task_id}: "
                            f"{fact.statement}",
                        )
                    )

                if execution.message:

                    evidence.append(
                        cls._bound_text(
                            f"Task {task_id}: "
                            f"{execution.message}",
                        )
                    )

                if execution.return_code is not None:

                    evidence.append(
                        cls._bound_text(
                            f"Task {task_id}: "
                            f"return code "
                            f"{execution.return_code}",
                        )
                    )

                if processed.artifact_decision.artifact:

                    evidence.append(
                        cls._bound_text(
                            f"Task {task_id}: "
                            f"{processed.artifact_decision.artifact.summary}",
                        )
                    )

        return evidence[
            -_MAX_RESULTS:
        ]

    # ==========================================================
    # Artifacts
    # ==========================================================

    @classmethod
    def _build_artifacts(
        cls,
        state: TerminalState,
    ) -> list[OutputArtifact]:

        references = state.get(
            "artifact_references",
            [],
        )

        return [
            OutputArtifact(
                artifact_id=reference.artifact_id,
                artifact_type=reference.artifact_type,
                summary=cls._bound_text(
                    reference.summary,
                ),
                source=reference.source,
            )
            for reference in references[
                -_MAX_ARTIFACTS:
            ]
        ]

    # ==========================================================
    # Decision
    # ==========================================================

    @classmethod
    def _build_decision(
        cls,
        decision_context: RuntimeDecisionContext | None,
    ) -> OutputDecision | None:

        if decision_context is None:
            return None

        return OutputDecision(
            rationale=cls._bound_text(
                decision_context.rationale,
            ),
            evidence=[
                cls._bound_text(
                    f"{evidence.source}: "
                    f"{evidence.observation}",
                )
                for evidence in decision_context.evidence[
                    -_MAX_ERRORS:
                ]
            ],
        )

    # ==========================================================
    # Text Bound
    # ==========================================================

    @staticmethod
    def _bound_text(
        value: Any,
        limit: int = _MAX_TEXT_LENGTH,
    ) -> str:

        text = str(
            value
        ).strip()

        if len(text) <= limit:
            return text

        return (
            text[
                : limit - 3
            ].rstrip()
            + "..."
        )


__all__ = [
    "OutputContextBuilder",
]