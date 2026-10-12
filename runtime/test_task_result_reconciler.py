import pytest

from models import ActiveTaskMemory, ExecutionMemory

from result_processing.models import (
    ArtifactAction,
    ArtifactCandidate,
    ArtifactDecision,
    ExecutionOutcome,
    Fact,
    MemoryUpdateProposal,
    NormalizedResult,
    RuntimeProcessingResult,
    ToolExecutionContext,
)

from runtime import task_result_reconciler as reconciler_module
from runtime.task_execution import (
    TaskExecutionResult,
    TaskExecutionStatus,
)
from runtime.task_result_reconciler import (
    MAX_TASK_EVIDENCE_ENTRIES,
    TaskResultReconciler,
)
from task_plan.models import (
    TaskItem,
    TaskItemStatus,
    TaskPlan,
    TaskPlanStatus,
)


def build_plan(
    *,
    first_status: TaskItemStatus = TaskItemStatus.IN_PROGRESS,
) -> TaskPlan:
    return TaskPlan(
        plan_id="plan-1",
        goal="explain the repository layout",
        status=TaskPlanStatus.ACTIVE,
        tasks=[
            TaskItem(
                task_id="a1",
                objective="Identify the core goal",
                status=first_status,
                success_criteria=["The core goal is named"],
            ),
            TaskItem(
                task_id="a2",
                objective="Persist the discovered knowledge",
                status=TaskItemStatus.READY,
            ),
        ],
    )


def build_state() -> dict:
    return {
        "artifact_references": [],
        "execution_memory": ExecutionMemory(),
        "active_memory": ActiveTaskMemory(),
    }


def build_processing_result(
    *,
    evidence: list[str] | None = None,
    message: str | None = "Verified the requirement.",
    store_artifact: bool = False,
) -> RuntimeProcessingResult:
    artifact = None
    artifact_action = ArtifactAction.SKIP

    if store_artifact:
        artifact_action = ArtifactAction.STORE
        artifact = ArtifactCandidate(
            artifact_type="markdown",
            summary="Core goal summary",
            data={"body": "documented"},
        )

    return RuntimeProcessingResult(
        normalized_result=NormalizedResult(
            context=ToolExecutionContext(
                tool_name="read_file",
            ),
            execution=ExecutionOutcome(
                success=True,
                progress_made=True,
                message=message,
            ),
            facts=[
                Fact(
                    statement="The core goal is documented.",
                    source="read_file",
                )
            ],
        ),
        artifact_decision=ArtifactDecision(
            action=artifact_action,
            reason="The result is decision-relevant.",
            artifact=artifact,
        ),
        memory_update=MemoryUpdateProposal(
            evidence=list(evidence or []),
        ),
    )


def build_result(
    *,
    status: TaskExecutionStatus,
    processing_results: list[RuntimeProcessingResult] | None = None,
    error: str | None = None,
) -> TaskExecutionResult:
    return TaskExecutionResult(
        execution_id="exec-1",
        plan_id="plan-1",
        task_id="a1",
        status=status,
        error=error,
        processing_results=processing_results or [],
    )


def reconcile(plan, results, state):
    return TaskResultReconciler.reconcile(
        plan=plan,
        results=results,
        state=state,
    )


def test_reconciler_attributes_proposal_and_execution_evidence():
    plan = build_plan()
    state = build_state()

    result = build_result(
        status=TaskExecutionStatus.COMPLETED,
        processing_results=[
            build_processing_result(
                evidence=[
                    "The README documents the module.",
                    "The routing table matches the code.",
                ],
            )
        ],
    )

    reconcile(plan, [result], state)

    task = plan.tasks[0]

    assert task.status == TaskItemStatus.COMPLETED
    assert "The README documents the module." in task.evidence
    assert "The routing table matches the code." in task.evidence
    assert (
        "read_file: Verified the requirement." in task.evidence
    )
    assert task.confirmed is False


def test_reconciler_records_error_evidence_on_failed_task():
    plan = build_plan()
    state = build_state()

    result = build_result(
        status=TaskExecutionStatus.FAILED,
        error="The worker crashed before producing output.",
    )

    reconcile(plan, [result], state)

    task = plan.tasks[0]

    assert task.status == TaskItemStatus.FAILED
    assert (
        "error: The worker crashed before producing output."
        in task.evidence
    )


def test_task_evidence_is_bounded(monkeypatch):
    monkeypatch.setattr(
        reconciler_module.artifact_store,
        "save",
        lambda **kwargs: "art-1",
    )
    monkeypatch.setattr(
        TaskResultReconciler,
        "_associate_artifact_with_attempt",
        staticmethod(lambda **kwargs: None),
    )

    plan = build_plan()
    state = build_state()

    result = build_result(
        status=TaskExecutionStatus.COMPLETED,
        processing_results=[
            build_processing_result(
                evidence=[
                    f"evidence line {index}"
                    for index in range(20)
                ],
            )
        ],
    )

    reconcile(plan, [result], state)

    task = plan.tasks[0]

    assert len(task.evidence) <= MAX_TASK_EVIDENCE_ENTRIES
    assert "evidence line 19" in task.evidence
    assert "evidence line 0" not in task.evidence


def test_persisted_artifact_summary_is_attributed(monkeypatch):
    monkeypatch.setattr(
        reconciler_module.artifact_store,
        "save",
        lambda **kwargs: "art-1",
    )
    monkeypatch.setattr(
        TaskResultReconciler,
        "_associate_artifact_with_attempt",
        staticmethod(lambda **kwargs: None),
    )

    plan = build_plan()
    state = build_state()

    result = build_result(
        status=TaskExecutionStatus.COMPLETED,
        processing_results=[
            build_processing_result(
                store_artifact=True,
            )
        ],
    )

    reconcile(plan, [result], state)

    task = plan.tasks[0]

    assert "artifact: Core goal summary" in task.evidence
    assert state["artifact_references"][0].artifact_id == "art-1"


def test_reconciled_task_starts_unconfirmed_with_criteria():
    plan = build_plan()
    state = build_state()

    result = build_result(
        status=TaskExecutionStatus.COMPLETED,
    )

    reconcile(plan, [result], state)

    task = plan.tasks[0]

    assert task.confirmed is False
    assert task.success_criteria == ["The core goal is named"]
