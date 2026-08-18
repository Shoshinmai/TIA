from agents.terminal.task_executor.models import ExecutionStep, ExecutionStepStatus, ExecutionWorkflow, WorkflowStatus
from agents.terminal.runtime.consistency import validate_runtime_consistency
from agents.terminal.runtime.models import RuntimeState
from agents.terminal.runtime.modes import RuntimeMode
from agents.terminal.task_plan.models import TaskItem, TaskItemStatus, TaskPlan, TaskPlanStatus
import pytest


def test_executing_state_is_consistent():

    task = TaskItem(
        task_id="task-1",
        objective="Inspect planner.py",
        status=TaskItemStatus.IN_PROGRESS,
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect planner",
        tasks=[task],
    )

    state = {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.EXECUTING,
        ),
        "task_plan": plan,
        "execution_workflow": None,
    }

    validate_runtime_consistency(state)
    
def test_executing_requires_in_progress_task():

    task = TaskItem(
        task_id="task-1",
        objective="Inspect planner.py",
        status=TaskItemStatus.READY,
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect planner",
        tasks=[task],
    )

    state = {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.EXECUTING,
        ),
        "task_plan": plan,
    }

    with pytest.raises(RuntimeError):
        validate_runtime_consistency(state)
        
def test_only_one_task_can_be_in_progress():

    task_a = TaskItem(
        task_id="A",
        objective="Inspect planner.py",
        status=TaskItemStatus.IN_PROGRESS,
    )

    task_b = TaskItem(
        task_id="B",
        objective="Inspect executor.py",
        status=TaskItemStatus.IN_PROGRESS,
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect project",
        tasks=[task_a, task_b],
    )

    state = {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.EXECUTING,
        ),
        "task_plan": plan,
    }

    with pytest.raises(RuntimeError):
        validate_runtime_consistency(state)
        
def test_workflow_must_match_current_task():

    task = TaskItem(
        task_id="A",
        objective="Inspect planner.py",
        status=TaskItemStatus.IN_PROGRESS,
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect project",
        tasks=[task],
    )

    workflow = ExecutionWorkflow(
        workflow_id="workflow-1",
        objective="Inspect executor.py",
        execution_strategy="Inspect executor",
        steps=[
            ExecutionStep(
                step_id="step-1",
                description="Read executor.py",
                capability="read_file",
                arguments={
                    "path": "executor.py",
                },
            )
        ],
    )

    state = {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.EXECUTING,
        ),
        "task_plan": plan,
        "execution_workflow": workflow,
    }

    with pytest.raises(RuntimeError):
        validate_runtime_consistency(state)
        
def test_reviewing_completed_workflow_is_valid():

    task = TaskItem(
        task_id="A",
        objective="Inspect planner.py",
        status=TaskItemStatus.IN_PROGRESS,
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect project",
        tasks=[task],
    )

    workflow = ExecutionWorkflow(
        workflow_id="workflow-1",
        objective="Inspect planner.py",
        execution_strategy="Read the planner",
        steps=[
            ExecutionStep(
                step_id="step-1",
                description="Read planner.py",
                capability="read_file",
                arguments={},
                status=ExecutionStepStatus.COMPLETED,
            )
        ],
        status=WorkflowStatus.COMPLETED,
    )

    state = {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.REVIEWING,
        ),
        "task_plan": plan,
        "execution_workflow": workflow,
    }

    validate_runtime_consistency(state)
    
def test_reviewing_paused_workflow_is_valid():

    task = TaskItem(
        task_id="A",
        objective="Inspect planner.py",
        status=TaskItemStatus.IN_PROGRESS,
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect project",
        tasks=[task],
    )

    workflow = ExecutionWorkflow(
        workflow_id="workflow-1",
        objective="Inspect planner.py",
        execution_strategy="Read the planner",
        steps=[
            ExecutionStep(
                step_id="step-1",
                description="Read planner.py",
                capability="read_file",
                arguments={},
                status=ExecutionStepStatus.FAILED,
            )
        ],
        status=WorkflowStatus.PAUSED,
    )

    state = {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.REVIEWING,
        ),
        "task_plan": plan,
        "execution_workflow": workflow,
    }

    validate_runtime_consistency(state)
    
def test_executing_cannot_have_completed_workflow():

    task = TaskItem(
        task_id="A",
        objective="Inspect planner.py",
        status=TaskItemStatus.IN_PROGRESS,
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect project",
        tasks=[task],
    )

    workflow = ExecutionWorkflow(
        workflow_id="workflow-1",
        objective="Inspect planner.py",
        execution_strategy="Read planner",
        steps=[
            ExecutionStep(
                step_id="step-1",
                description="Read planner",
                capability="read_file",
                arguments={},
                status=ExecutionStepStatus.COMPLETED,
            )
        ],
        status=WorkflowStatus.COMPLETED,
    )

    state = {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.EXECUTING,
        ),
        "task_plan": plan,
        "execution_workflow": workflow,
    }

    with pytest.raises(RuntimeError):
        validate_runtime_consistency(state)
        
def test_finished_requires_completed_plan():

    task = TaskItem(
        task_id="A",
        objective="Inspect planner.py",
        status=TaskItemStatus.COMPLETED,
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect project",
        status=TaskPlanStatus.CREATED,
        tasks=[task],
    )

    state = {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.FINISHED,
        ),
        "task_plan": plan,
    }

    with pytest.raises(RuntimeError):
        validate_runtime_consistency(state)
        
def test_finished_completed_plan_is_valid():

    task = TaskItem(
        task_id="A",
        objective="Inspect planner.py",
        status=TaskItemStatus.COMPLETED,
    )

    plan = TaskPlan(
        plan_id="plan-1",
        goal="Inspect project",
        status=TaskPlanStatus.COMPLETED,
        tasks=[task],
    )

    state = {
        "runtime_state": RuntimeState(
            mode=RuntimeMode.FINISHED,
        ),
        "task_plan": plan,
    }

    validate_runtime_consistency(state)