from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode

from nodes.tool_compiler import (
    compile_execution_step,
)
from task_executor.models import (
    ExecutionWorkflow,
    WorkflowStatus,
)
from task_executor.workflow_manager import (
    WorkflowManager,
)
from tools import TOOLS


class WorkflowRuntime:
    """
    Deterministic runtime for executing an ExecutionWorkflow.

    The runtime executes one workflow step at a time.

    Responsibilities:
    - compile the current ExecutionStep
    - invoke the selected capability
    - extract the actual tool payload from ToolNode output
    - update workflow step lifecycle
    - return the task-local execution result

    The runtime does not:
    - reason about the objective
    - create workflows
    - select capabilities
    - retry failed steps
    - call the Critic
    - perform replanning
    - process semantic memory
    - mutate TerminalState
    """

    def __init__(
        self,
        *,
        tool_node: ToolNode | None = None,
        step_listener: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:

        self.tool_node = (
            tool_node
            if tool_node is not None
            else ToolNode(TOOLS)
        )

        self.step_listener = step_listener

    async def execute_next_step(
        self,
        workflow: ExecutionWorkflow,
    ) -> dict:
        """
        Execute the current workflow step asynchronously.

        Returns:

            workflow
            tool_result
            completed
            step_id
            capability

        `tool_result` is the actual capability payload, not the
        LangGraph ToolNode response envelope.

        Example:

            {
                "success": True,
                "output": "...",
                "error": "",
                "return_code": 0,
            }
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
                "step_id": None,
                "capability": None,
            }

        step_id = step.step_id
        capability = step.capability

        WorkflowManager.start_step(
            workflow=workflow,
            step_id=step_id,
        )

        if self.step_listener is not None:
            try:
                self.step_listener(
                    {
                        "step_id": step_id,
                        "capability": capability,
                        "workflow": workflow.model_dump(mode="json"),
                    }
                )
            except Exception:
                pass

        try:

            # ==================================================
            # 1. Compile workflow step into a ToolCall
            # ==================================================

            tool_call_message = compile_execution_step(
                step=step,
            )

            # ==================================================
            # 2. Invoke the actual ToolNode
            # ==================================================

            tool_node_result = await self.tool_node.ainvoke(
                {
                    "messages": [
                        tool_call_message,
                    ]
                },
            )

        except Exception:

            WorkflowManager.fail_step(
                workflow=workflow,
                step_id=step_id,
            )

            raise

        # ======================================================
        # 3. Extract the actual tool result
        # ======================================================

        tool_result = self._extract_tool_result(
            tool_node_result,
            capability=capability,
        )

        # ======================================================
        # 4. Update workflow lifecycle
        # ======================================================

        self._handle_tool_result(
            workflow=workflow,
            step_id=step_id,
            tool_result=tool_result,
        )

        return {
            "workflow": workflow,
            "tool_result": tool_result,
            "completed": (
                workflow.status.value == "completed"
            ),
            "step_id": step_id,
            "capability": capability,
        }

    @staticmethod
    def _extract_tool_result(
        tool_node_result: dict[str, Any],
        *,
        capability: str,
    ) -> dict[str, Any]:
        """
        Extract the actual capability result from the LangGraph
        ToolNode response.

        ToolNode returns an envelope such as:

            {
                "messages": [
                    ToolMessage(
                        content='{"success": true, ...}',
                        name="run_terminal",
                        ...
                    )
                ]
            }

        The Runtime Processing Pipeline expects the actual
        capability payload:

            {
                "success": true,
                ...
            }

        This method therefore forms the boundary between the
        LangGraph ToolNode representation and CASO's normalized
        tool-result representation.
        """

        if not isinstance(
            tool_node_result,
            dict,
        ):
            raise ValueError(
                "ToolNode returned an invalid response for "
                f"capability '{capability}': "
                f"expected dict, got "
                f"{type(tool_node_result).__name__}."
            )

        messages = tool_node_result.get(
            "messages",
            [],
        )

        if not messages:
            raise ValueError(
                "ToolNode returned no messages for capability "
                f"'{capability}'."
            )

        tool_messages = [
            message
            for message in messages
            if isinstance(
                message,
                ToolMessage,
            )
        ]

        if not tool_messages:
            raise ValueError(
                "ToolNode returned no ToolMessage for capability "
                f"'{capability}'."
            )

        # The current workflow invokes one tool per step.
        # Therefore the latest ToolMessage is the authoritative
        # result for this execution step.
        tool_message = tool_messages[-1]

        # ------------------------------------------------------
        # Tool execution failure
        # ------------------------------------------------------

        if tool_message.status == "error":

            return {
                "success": False,
                "output": "",
                "error": str(
                    tool_message.content
                ),
            }

        content = tool_message.content

        # ------------------------------------------------------
        # Tool implementations may return structured content
        # directly.
        # ------------------------------------------------------

        if isinstance(
            content,
            dict,
        ):

            return content

        # ------------------------------------------------------
        # LangGraph commonly serializes structured tool output
        # into a JSON string inside ToolMessage.content.
        # ------------------------------------------------------

        if isinstance(
            content,
            str,
        ):

            try:

                decoded = json.loads(
                    content,
                )

            except json.JSONDecodeError:

                # Preserve non-JSON textual tool output.
                return {
                    "success": True,
                    "output": content,
                    "error": "",
                }

            if isinstance(
                decoded,
                dict,
            ):

                return decoded

            # A JSON scalar/list is still valid tool output,
            # but the current Result Processing Pipeline expects
            # a dictionary-shaped raw result.
            return {
                "success": True,
                "output": decoded,
                "error": "",
            }

        # ------------------------------------------------------
        # Fallback for unusual ToolMessage content types.
        # ------------------------------------------------------

        return {
            "success": True,
            "output": content,
            "error": "",
        }

    @staticmethod
    def _handle_tool_result(
        *,
        workflow: ExecutionWorkflow,
        step_id: str,
        tool_result: dict[str, Any],
    ) -> None:
        """
        Update workflow state according to the immediate
        ToolNode execution result.

        This determines whether the capability invocation itself
        succeeded.

        It does not evaluate semantic task progress.
        """

        if tool_result.get("success") is False:

            WorkflowManager.fail_step(
                workflow=workflow,
                step_id=step_id,
            )
            workflow.status = WorkflowStatus.FAILED

            return

        WorkflowManager.complete_step(
            workflow=workflow,
            step_id=step_id,
        )