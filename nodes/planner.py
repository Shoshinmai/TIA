from agents.terminal.memory import artifact_store
from agents.terminal.models import PlanningOutput, TaskPlanningOutput
from agents.terminal.prompts.planner_prompt import TERMINAL_PLANNER_PROMPT
from agents.terminal.runtime.events import RuntimeEvent
from agents.terminal.state import TerminalState
from agents.terminal.task_plan.manager import TaskPlanManager
from agents.terminal.task_plan.materializer import TaskPlanMaterializer
from agents.terminal.utils.planner_context_builder import build_planner_context
from llm.llmclient import call_nvidia, call_ollama


def terminal_planner_node(state: TerminalState):

    planner_context = build_planner_context(
        state=state,
    )

    print("\n========== ACTIVE MEMORY ==========")
    print(planner_context["active_memory"])

    prompt = TERMINAL_PLANNER_PROMPT.format(**planner_context)

    # plan = call_ollama(
    #     prompt=prompt,
    #     model="deepseek-r1:8b",
    #     # model="qwen2.5-coder:7b",
    #     # model="freehuntx/qwen3-coder:8b ",
    #     subagent=True,
    #     state_model=TaskPlanningOutput,
    # )
    plan = call_nvidia(
        prompt,
        # "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3-super-120b-a12b",
        subagent=True,
        state_model=TaskPlanningOutput,
    )

    runtime_state = state.get("runtime_state")

    is_plan_update = (
        runtime_state is not None
        and runtime_state.last_event == RuntimeEvent.PLAN_UPDATE_REQUIRED
    )
    
    is_replan = (
        runtime_state is not None
        and runtime_state.last_event == RuntimeEvent.REPLAN_REQUIRED
    )

    # ----------------------------------------------------------
    # PLAN UPDATE
    # ----------------------------------------------------------

    if is_plan_update:

        update_current_task_plan(
            state=state,
            planning_output=plan,
        )

        task_plan = state["task_plan"]

    # ----------------------------------------------------------
    # REPLAN
    # ----------------------------------------------------------

    elif is_replan:

        replan_current_task_plan(
            state=state,
            planning_output=plan,
        )

        task_plan = state["task_plan"]

    # ----------------------------------------------------------
    # INITIAL PLAN
    # ----------------------------------------------------------

    else:

        task_plan = TaskPlanMaterializer.materialize(
            goal=state.get("task").goal,
            planning_output=plan,
        )

        state["task_plan"] = task_plan

    if runtime_state is not None:
        runtime_state.decision_context = None

    print("\n========== TASK PLANNER ==========")
    print(task_plan.model_dump())

    return {
        "task_plan": task_plan,
        "planner_output": plan,
    }


def update_current_task_plan(
    *,
    state: TerminalState,
    planning_output: TaskPlanningOutput,
) -> None:
    """
    Apply a Planner-generated rolling-plan update to the existing
    TaskPlan.

    The Planner proposes the new task structure.
    TaskPlanManager owns the mutation.
    """

    task_plan = state.get("task_plan")

    if task_plan is None:
        raise ValueError("Cannot update TaskPlan because no existing TaskPlan exists.")

    proposed_plan = TaskPlanMaterializer.materialize(
        goal=task_plan.goal,
        planning_output=planning_output,
    )

    TaskPlanManager.update_remaining_tasks(
        plan=task_plan,
        tasks=proposed_plan.tasks,
    )

    task_plan.metadata = proposed_plan.metadata

    TaskPlanManager.update_task_readiness(
        plan=task_plan,
    )


def replan_current_task_plan(
    *,
    state: TerminalState,
    planning_output: TaskPlanningOutput,
) -> None:
    """
    Replace the remaining portion of the current TaskPlan with
    a newly generated planning strategy.

    Completed tasks are preserved so execution history remains
    part of the current TaskPlan.

    The Planner proposes the new structure.
    TaskPlanManager owns the mutation.
    """

    task_plan = state.get("task_plan")

    if task_plan is None:
        raise ValueError("Cannot replan because no existing TaskPlan exists.")

    proposed_plan = TaskPlanMaterializer.materialize(
        goal=task_plan.goal,
        planning_output=planning_output,
    )

    TaskPlanManager.replace_remaining_tasks(
        plan=task_plan,
        tasks=proposed_plan.tasks,
    )

    task_plan.metadata = proposed_plan.metadata

    TaskPlanManager.update_task_readiness(
        plan=task_plan,
    )
