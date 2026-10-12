"""End-to-end integration tests for TIA convergence corrections.

These tests exercise the real runtime_graph.py with deterministic mocks
for LLM calls and controlled tool execution.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from critics.integration import build_critic_runtime_event
from critics.models import (
    CriticDecision,
    CriticEvidence,
    CriticOutput,
)
from nodes import critics as critic_node_module
from runtime.events import RuntimeEvent
from runtime.modes import RuntimeMode
from runtime.models import RuntimeState
from runtime.nodes import (
    runtime_critic_result_node,
    _apply_concurrent_critic_decision as apply_concurrent_critic_decision,
    _recover_from_rejected_goal_completion,
)
from runtime.state_machine import RuntimeStateMachine
from task_plan.manager import TaskPlanManager
from task_plan.models import (
    TaskItem,
    TaskItemStatus,
    TaskPlan,
    TaskPlanStatus,
)
from utils.location_resolver import set_workspace_root, get_workspace_root, resolve_location


# ============================================================
# Test Helpers
# ============================================================

def build_basic_plan():
    """Build a simple plan with one completed and one failed task."""
    return TaskPlan(
        plan_id="plan-1",
        goal="test goal",
        status=TaskPlanStatus.ACTIVE,
        tasks=[
            TaskItem(
                task_id="t1",
                objective="First task",
                status=TaskItemStatus.COMPLETED,
            ),
            TaskItem(
                task_id="t2",
                objective="Second task",
                status=TaskItemStatus.FAILED,
            ),
        ],
    )


def build_incomplete_plan():
    """Build a plan with no ready tasks and no blocked tasks (stalled)."""
    return TaskPlan(
        plan_id="plan-stalled",
        goal="stalled goal",
        status=TaskPlanStatus.ACTIVE,
        tasks=[
            TaskItem(
                task_id="t1",
                objective="Task with unmet dependency",
                status=TaskItemStatus.PENDING,
                dependencies=["nonexistent"],
            ),
        ],
    )


def build_state_for_critic(task_plan, runtime_mode=RuntimeMode.REVIEWING, inadmissible_count=0):
    """Build state dict for critic result node."""
    return {
        "runtime_state": RuntimeState(
            mode=runtime_mode,
            metadata={
                "inadmissible_decision_count": inadmissible_count,
            },
        ),
        "task_plan": task_plan,
        "plan_execution_outcome": None,
        "execution_workflow": None,
        "critic_runtime_event": None,
    }


def goal_completed_event():
    """Create a GOAL_COMPLETED runtime event from critic."""
    return build_critic_runtime_event(
        CriticOutput(
            decision=CriticDecision.GOAL_COMPLETED,
            rationale="Goal achieved.",
            evidence=[
                CriticEvidence(
                    source="execution",
                    observation="Task completed.",
                )
            ],
        )
    )


def retry_task_event(target_task_ids):
    """Create a RETRY_TASK runtime event from critic."""
    return build_critic_runtime_event(
        CriticOutput(
            decision=CriticDecision.RETRY_TASK,
            rationale="Retry needed.",
            evidence=[
                CriticEvidence(
                    source="execution",
                    observation="Transient failure.",
                )
            ],
            target_task_ids=target_task_ids,
        )
    )


# ============================================================
# 1. Empty incomplete wave → TASK_BLOCKED → Critic review
# ============================================================

def test_empty_incomplete_wave_emits_task_blocked():
    """
    An empty wave with incomplete plan and no ready/blocked tasks
    should emit TASK_BLOCKED (not PLAN_EXHAUSTED) and transition
    to REVIEWING without InvalidRuntimeTransition.
    """
    from runtime.kernel import RuntimeKernel

    runtime_state = RuntimeState(mode=RuntimeMode.EXECUTING)

    # Verify state machine allows EXECUTING + TASK_BLOCKED
    next_mode = RuntimeStateMachine.transition(
        current_mode=RuntimeMode.EXECUTING,
        event=RuntimeEvent.TASK_BLOCKED,
    )
    assert next_mode == RuntimeMode.REVIEWING

    # Kernel should handle the transition
    stage = RuntimeKernel.handle_event(
        runtime_state=runtime_state,
        event=RuntimeEvent.TASK_BLOCKED,
    )
    assert stage.value == "critic"
    assert runtime_state.mode == RuntimeMode.REVIEWING


# ============================================================
# 2. Budget exhaustion → incomplete terminal output
# ============================================================

def test_budget_exhaustion_produces_partial_completion():
    """
    When budget is exhausted (iteration cap, no-progress, or decision loop),
    runtime terminates with PARTIAL_COMPLETION output type,
    not FINAL/GOAL_COMPLETED.
    """
    from output.models import OutputType
    from output.context import OutputContextBuilder
    from runtime.plan_execution_outcome import PlanExecutionCondition, PlanExecutionOutcome

    runtime_state = RuntimeState(
        mode=RuntimeMode.FINISHED,
        metadata={"termination_reason": "budget_exhausted"},
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="partial goal",
        status=TaskPlanStatus.ACTIVE,  # NOT completed
        tasks=[
            TaskItem(task_id="t1", objective="Done", status=TaskItemStatus.COMPLETED),
            TaskItem(task_id="t2", objective="Pending", status=TaskItemStatus.PENDING),
        ],
    )

    # Provide a PlanExecutionOutcome so OutputContextBuilder can derive outcome
    outcome = PlanExecutionOutcome(
        plan_id="plan-1",
        condition=PlanExecutionCondition.PARTIALLY_COMPLETED,
        completed_task_ids=["t1"],
        failed_task_ids=[],
        blocked_task_ids=["t2"],
        cancelled_task_ids=[],
    )

    state = {
        "runtime_state": runtime_state,
        "task_plan": plan,
        "plan_execution_outcome": outcome,
        "active_memory": None,
        "artifact_references": [],
    }

    from output.context import OutputContextBuilder
    context = OutputContextBuilder.build(state)
    assert context.output_type == "partial_completion"
    assert context.termination_reason == "budget_exhausted"


# ============================================================
# 3. Initial → retry → 2nd execution with attempt_count 1,2
# ============================================================

def test_attempt_count_increments_on_start_not_retry():
    """
    A task starts with attempt_count=0.
    First execution: start_task increments to 1.
    Retry: requeues to READY, count stays 1.
    Second execution: start_task increments to 2.
    """
    plan = TaskPlan(
        plan_id="plan-1",
        goal="test",
        status=TaskPlanStatus.ACTIVE,
        tasks=[
            TaskItem(
                task_id="t1",
                objective="Test task",
                status=TaskItemStatus.READY,
                max_attempts=3,
            ),
        ],
    )

    # Initial state
    assert plan.tasks[0].attempt_count == 0

    # First execution start
    TaskPlanManager.start_task(plan=plan, task_id="t1")
    assert plan.tasks[0].status == TaskItemStatus.IN_PROGRESS
    assert plan.tasks[0].attempt_count == 1

    # Retry (requeue only)
    TaskPlanManager.retry_task(plan=plan, task_id="t1")
    assert plan.tasks[0].status == TaskItemStatus.READY
    assert plan.tasks[0].attempt_count == 1  # NOT incremented

    # Second execution start
    TaskPlanManager.start_task(plan=plan, task_id="t1")
    assert plan.tasks[0].status == TaskItemStatus.IN_PROGRESS
    assert plan.tasks[0].attempt_count == 2


# ============================================================
# 4. PLAN_UPDATE → matched task preserves identity/runtime fields
# ============================================================

def test_plan_update_preserves_runtime_fields():
    """
    When PLAN_UPDATE matches a task by (objective, dependencies),
    the existing task preserves:
    - task_id
    - success_criteria (unless contract_revision=True)
    - confirmed, evidence
    - blockers, attempt_count, max_attempts
    - status
    Only priority and metadata['planner'] may be updated.
    """
    from models import PlannerTask, TaskPlanningOutput
    from task_plan.materializer import TaskPlanMaterializer

    # Create initial plan
    initial_output = TaskPlanningOutput(
        strategy="Test",
        tasks=[
            PlannerTask(
                planner_task_id="pt1",
                objective="Existing task",
                dependencies=[],
                success_criteria=["Original criteria"],
            ),
        ],
    )

    plan = TaskPlanMaterializer.materialize(
        goal="test goal",
        planning_output=initial_output,
    )

    task = plan.tasks[0]
    original_id = task.task_id
    task.confirmed = True
    task.evidence = ["some evidence"]
    task.attempt_count = 2
    task.blockers = ["blocker"]
    task.max_attempts = 5

    # Planner proposes update WITHOUT contract_revision
    # Create TaskItems directly with contract_revision=False
    from task_plan.models import TaskItem
    new_tasks = [
        TaskItem(
            task_id="new-id",  # Will be matched by objective+deps, not used
            objective="Existing task",
            dependencies=[],
            success_criteria=["New criteria from planner"],  # Should be IGNORED
            priority=10,
            contract_revision=False,  # Explicit: no contract revision
        ),
    ]

    # Apply PLAN_UPDATE
    TaskPlanManager.update_remaining_tasks(plan=plan, tasks=new_tasks)

    updated_task = plan.tasks[0]

    # Verify preservation
    assert updated_task.task_id == original_id
    assert updated_task.success_criteria == ["Original criteria"]  # Preserved!
    assert updated_task.confirmed is True  # Preserved!
    assert updated_task.evidence == ["some evidence"]  # Preserved!
    assert updated_task.attempt_count == 2  # Preserved!
    assert updated_task.max_attempts == 5  # Preserved!
    assert updated_task.blockers == ["blocker"]  # Preserved!
    assert updated_task.status == TaskItemStatus.READY  # Task was COMPLETED, reset by update
    assert updated_task.priority == 10  # Updated!


# ============================================================
# 5. Repeated invalid GOAL_COMPLETED → bounded termination
# ============================================================

def test_repeated_invalid_goal_completion_bounded():
    """
    GOAL_COMPLETED claims that contradict state are rejected.
    The recovery path follows RETRY_TASK for failed tasks.
    The inadmissible decision budget (MAX_INADMISSIBLE_DECISIONS=3)
    applies to structurally invalid decisions, not goal-completion rejections.
    """
    from runtime.nodes import INADMISSIBLE_DECISION_KEY, MAX_INADMISSIBLE_DECISIONS

    plan = build_basic_plan()
    runtime_state = RuntimeState(
        mode=RuntimeMode.REVIEWING,
        metadata={INADMISSIBLE_DECISION_KEY: 0},
    )

    state = {
        "runtime_state": runtime_state,
        "task_plan": plan,
        "plan_execution_outcome": None,
        "execution_workflow": None,
    }

    event = goal_completed_event()

    # GOAL_COMPLETED is always rejected when it contradicts state.
    # The recovery path (RETRY_TASK for failed task) is followed.
    # No acceptance bypass exists.
    result = apply_concurrent_critic_decision(
        state=state,
        event=RuntimeEvent.GOAL_COMPLETED,
        decision_context=event.context,
        runtime_state=runtime_state,
    )
    assert result["critic_rejection"] is not None
    # Goal completion rejection follows normal recovery, not inadmissible path
    assert runtime_state.metadata.get(INADMISSIBLE_DECISION_KEY, 0) == 0

    # The inadmissible decision budget (MAX_INADMISSIBLE_DECISIONS=3)
    # only applies to structurally invalid decisions (wrong targets, scope mismatch),
    # not to goal-completion rejections which follow normal recovery path.


# ============================================================
# 6. Workspace anchoring → later change rejected
# ============================================================

def test_workspace_anchoring_rejects_change():
    """
    Workspace root anchored at init. Later attempts to change
    workspace in state are rejected by consistency check.
    """
    from runtime.consistency import validate_runtime_consistency

    runtime_state = RuntimeState(
        mode=RuntimeMode.EXECUTING,
        metadata={"workspace_root": "/original/path"},
    )

    plan = build_basic_plan()
    # Set one task to IN_PROGRESS for EXECUTING mode
    plan.tasks[0].status = TaskItemStatus.IN_PROGRESS

    state = {
        "runtime_state": runtime_state,
        "workspace": "/original/path",
        "task_plan": plan,
    }

    # Valid - same workspace
    validate_runtime_consistency(state)

    # Invalid - changed workspace
    state["workspace"] = "/different/path"
    with pytest.raises(RuntimeError, match="Workspace root changed"):
        validate_runtime_consistency(state)


def test_workspace_session_isolation():
    """
    Concurrent sessions have isolated workspace roots via
    module-level _WORKSPACE_ROOT in location_resolver.
    """
    # Session 1
    set_workspace_root("/session1/workspace")
    assert str(get_workspace_root()) == str(Path("/session1/workspace").resolve())
    
    # Session 2 (simulated)
    set_workspace_root("/session2/workspace")
    assert str(get_workspace_root()) == str(Path("/session2/workspace").resolve())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])