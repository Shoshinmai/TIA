from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from agents.terminal.nodes.tool_compiler import (
    compile_execution_step,
)
from agents.terminal.task_executor.models import (
    ExecutionWorkflow,
)
from agents.terminal.task_executor.workflow_manager import (
    WorkflowManager,
)
from agents.terminal.tools import TOOLS


class WorkflowRuntime:
    """
    Deterministic runtime for executing an ExecutionWorkflow.

    The runtime executes one workflow step at a time.

    It does not:
    - reason about the objective
    - create workflows
    - select capabilities
    - retry failed steps
    - call the Critic
    - perform replanning
    """

    def __init__(
        self,
        *,
        tool_node: ToolNode | None = None,
    ) -> None:
        self.tool_node = (
            tool_node
            if tool_node is not None
            else ToolNode(TOOLS)
        )

    def execute_next_step(
        self,
        workflow: ExecutionWorkflow,
    ) -> dict:
        """
        Execute the current workflow step.

        Returns the ToolNode result so that the existing
        observation/result-processing pipeline can consume it.
        """

        if workflow.status.value == "pending":
            WorkflowManager.start(
                workflow=workflow,
            )

        step = WorkflowManager.get_current_step(
            workflow,
        )

        if step is None:
            return {
                "workflow": workflow,
                "tool_result": None,
                "completed": (
                    workflow.status.value == "completed"
                ),
            }

        WorkflowManager.start_step(
            workflow=workflow,
            step_id=step.step_id,
        )

        try:
            tool_call_message = compile_execution_step(
                step=step,
            )

            tool_result = self.tool_node.invoke(
                {
                    "messages": [
                        tool_call_message,
                    ]
                }
            )

        except Exception:
            WorkflowManager.fail_step(
                workflow=workflow,
                step_id=step.step_id,
            )
            raise

        self._handle_tool_result(
            workflow=workflow,
            step_id=step.step_id,
            tool_result=tool_result,
        )

        return {
            "workflow": workflow,
            "tool_result": tool_result,
            "completed": (
                workflow.status.value == "completed"
            ),
        }

    @staticmethod
    def _handle_tool_result(
        *,
        workflow: ExecutionWorkflow,
        step_id: str,
        tool_result: dict,
    ) -> None:
        """
        Update workflow state according to the immediate
        ToolNode execution result.

        This only determines whether the tool invocation itself
        succeeded. It does not evaluate semantic task progress.
        """

        messages = tool_result.get(
            "messages",
            [],
        )

        if not messages:
            WorkflowManager.fail_step(
                workflow=workflow,
                step_id=step_id,
            )
            return

        tool_messages = [
            message
            for message in messages
            if isinstance(message, ToolMessage)
        ]

        if not tool_messages:
            WorkflowManager.fail_step(
                workflow=workflow,
                step_id=step_id,
            )
            return

        if any(
            message.status == "error"
            for message in tool_messages
        ):
            WorkflowManager.fail_step(
                workflow=workflow,
                step_id=step_id,
            )
            return

        WorkflowManager.complete_step(
            workflow=workflow,
            step_id=step_id,
        )