from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import web

from llm.llmclient import reset_stream_listener, set_stream_listener
from runtime.concurrent_task_executor import (
    reset_cancel_check,
    reset_concurrent_event_listener,
    set_cancel_check,
    set_concurrent_event_listener,
)
from runtime.nodes import runtime_stage_router
from runtime.stages import RuntimeStage
from runtime_graph import runtime_graph


HOST = os.getenv("TIA_HOST", "127.0.0.1")
PORT = int(os.getenv("TIA_PORT", "8787"))


class TaskSession:
    def __init__(self, goal: str) -> None:
        self.task_id = str(uuid.uuid4())
        self.goal = goal
        self.snapshot: dict[str, Any] = {
            "mode": "initializing",
            "last_event": None,
            "iteration": 0,
            "goal": goal,
            "task_plan": None,
            "execution_workflow": None,
            "terminal": [],
            "decision": None,
            "artifacts": [],
            "memory": {"active": [], "thread": [], "persistent": []},
            "observation": {"summary": "", "important_information": "", "conclusion": "", "raw": None},
            "execution_memory": [],
            "thinking": {"active": False, "model": "", "text": "", "started_at": None},
            "concurrent_flow": {"plan_id": None, "wave_status": "idle", "max_concurrency": 3, "tasks": [], "events": []},
            "backend": {"connected": True, "running": False, "error": None},
        }
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.runner_loop: asyncio.AbstractEventLoop | None = None
        self.runner_task: asyncio.Task[None] | None = None
        self.running = False
        self.cancel_requested = threading.Event()
        self.error: str | None = None
        self.lock = threading.Lock()
        self.last_thinking_publish = 0.0

    def publish(self, state: dict[str, Any], event: str | None = None) -> None:
        with self.lock:
            previous_snapshot = self.snapshot
            self.snapshot = snapshot_from_state(state, self.snapshot)
            self.snapshot["backend"] = {"connected": True, "running": True, "error": None}
            if event:
                self.snapshot["last_event"] = event
            if self.snapshot == previous_snapshot:
                return
            payload = dict(self.snapshot)
            subscribers = list(self.subscribers)
            loop = self.loop
        if loop is None:
            return
        for queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, payload)

    def sync_mode(self, mode: str) -> None:
        """Force the UI-facing mode when a graph state carries no usable mode."""
        with self.lock:
            if self.snapshot.get("mode") == mode:
                return
            self.snapshot["mode"] = mode
            payload = dict(self.snapshot)
            subscribers = list(self.subscribers)
            loop = self.loop
        if loop is None:
            return
        for queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, payload)

    def fail(self, error: Exception) -> None:
        with self.lock:
            self.error = str(error)
            self.snapshot["mode"] = "error"
            self.snapshot["last_event"] = "task_failed"
            self.snapshot["backend"] = {"connected": True, "running": False, "error": str(error)}
            self.snapshot["terminal"] = [
                *self.snapshot["terminal"],
                {"time": stamp(), "kind": "error", "text": f"TASK_FAILED  /  {error}"},
            ]
            payload = dict(self.snapshot)
            subscribers = list(self.subscribers)
            loop = self.loop
        if loop:
            for queue in subscribers:
                loop.call_soon_threadsafe(queue.put_nowait, payload)

    def cancelled(self) -> None:
        """Publish a terminal cancellation state after the runtime unwinds."""
        with self.lock:
            self.snapshot["mode"] = "finished"
            self.snapshot["last_event"] = "task_cancelled"
            self.snapshot["thinking"] = {**self.snapshot.get("thinking", {}), "active": False}
            self.snapshot["backend"] = {"connected": True, "running": False, "error": None}
            self.snapshot["terminal"] = [
                *self.snapshot["terminal"],
                {"time": stamp(), "kind": "system", "text": "TASK_CANCELLED  /  Agent run cancelled by user."},
            ][-80:]
            payload = dict(self.snapshot)
            subscribers = list(self.subscribers)
            loop = self.loop
        if loop is not None:
            for queue in subscribers:
                loop.call_soon_threadsafe(queue.put_nowait, payload)

    def thinking_update(self, status: str, model: str, text: str) -> None:
        with self.lock:
            thinking = dict(self.snapshot.get("thinking", {}))
            if status == "started":
                thinking = {"active": True, "model": model, "text": "", "started_at": stamp()}
            elif status == "chunk":
                thinking.update({"active": True, "model": model, "text": f"{thinking.get('text', '')}{text}"})
            else:
                thinking["active"] = False
                thinking["model"] = model
            self.snapshot["thinking"] = thinking
            now = time.monotonic()
            should_publish = status != "chunk" or now - self.last_thinking_publish >= 0.1
            if not should_publish:
                return
            self.last_thinking_publish = now
            payload = dict(self.snapshot)
            subscribers = list(self.subscribers)
            loop = self.loop
        if loop is not None:
            for queue in subscribers:
                loop.call_soon_threadsafe(queue.put_nowait, payload)

    def concurrent_update(self, event: dict[str, Any]) -> None:
        with self.lock:
            flow = dict(self.snapshot.get("concurrent_flow", {}))
            tasks = [dict(task) for task in flow.get("tasks", [])]
            task_id = event.get("task_id")
            matching = next((task for task in tasks if task.get("task_id") == task_id), None)
            if matching is None and task_id:
                matching = {
                    "task_id": task_id,
                    "objective": event.get("objective", ""),
                    "status": "in_progress",
                    "dependencies": [],
                }
                tasks.append(matching)
            if matching is not None:
                matching.update({key: value for key, value in event.items() if key not in {"plan_id", "task_id"}})
                if event.get("event") in {"worker_finished", "worker_reconciled"}:
                    matching["status"] = event.get("status", matching.get("status"))
                elif event.get("event") == "worker_failed":
                    matching["status"] = "failed"
                elif event.get("event") == "worker_cancelled":
                    matching["status"] = "cancelled"
                elif event.get("event") in {
                    "wave_started",
                    "worker_started",
                    "worker_running",
                    "worker_dispatched",
                }:
                    matching["status"] = "in_progress"
                self._mirror_task_status(task_id, matching.get("status"))
            if event.get("event") in {"workflow_created", "workflow_step_started"} and event.get("workflow"):
                self.snapshot["execution_workflow"] = event["workflow"]
            flow["plan_id"] = event.get("plan_id", flow.get("plan_id"))
            flow["wave_status"] = "reconciling" if event.get("event") == "worker_reconciled" else "running"
            flow["tasks"] = tasks
            flow["events"] = [*flow.get("events", []), {"time": stamp(), **event}][-100:]
            self.snapshot["concurrent_flow"] = flow
            self._route_concurrent_terminal(event, matching, task_id)
            payload = dict(self.snapshot)
            subscribers = list(self.subscribers)
            loop = self.loop
        if loop is not None:
            for queue in subscribers:
                loop.call_soon_threadsafe(queue.put_nowait, payload)

    def _mirror_task_status(self, task_id: str | None, status: str | None) -> None:
        if not task_id or not status:
            return
        plan = self.snapshot.get("task_plan")
        if not isinstance(plan, dict):
            return
        tasks = plan.get("tasks")
        if not isinstance(tasks, list):
            return
        for task in tasks:
            if isinstance(task, dict) and task.get("task_id") == task_id:
                task["status"] = status
                break

    def _route_concurrent_terminal(self, event: dict[str, Any], matching: dict[str, Any] | None, task_id: str | None) -> None:
        entries = list(self.snapshot.get("terminal", []))
        task_tag = task_id[:8] if task_id else ""
        name = event.get("event", "")
        objective = (matching.get("objective") if matching else None) or event.get("objective") or ""

        if name == "workflow_created":
            workflow = event.get("workflow") or {}
            steps = workflow.get("steps", []) if isinstance(workflow, dict) else []
            entries = append_terminal(entries, "system", f"TASK {task_tag}  /  {objective}  /  {len(steps)} step(s)")
        elif name == "tool_started":
            capability = event.get("capability") or ""
            command = event.get("command") or event.get("description") or ""
            entries = append_terminal(entries, "command", f"RUN  /  {capability}  /  {command}")
        elif name == "tool_finished":
            capability = event.get("capability") or ""
            label = capability.upper() or "TOOL"
            detail = preview_text(event.get("command") or "", limit=100)
            result = preview_text(event.get("output") or "", limit=800) if event.get("success") else preview_text(event.get("error") or "", limit=400)
            body = result or ("OK" if event.get("success") else "Tool execution failed")
            text = f"{label}  /  {detail}  /  {body}" if detail else f"{label}  /  {body}"
            entries = append_terminal(entries, "success" if event.get("success") else "error", text)
        elif name == "worker_failed":
            entries = append_terminal(entries, "error", f"WORKER_FAILED  /  {objective or task_tag}  /  {event.get('error') or 'Unknown failure'}")
        elif name == "worker_cancelled":
            entries = append_terminal(entries, "error", f"WORKER_CANCELLED  /  {objective or task_tag}")
        elif name == "worker_finished":
            entries = append_terminal(entries, "system", f"WORKER_FINISHED  /  {objective or task_tag}  /  {event.get('status') or ''}")
        elif name == "worker_reconciled":
            entries = append_terminal(entries, "system", f"WAVE_RECONCILED  /  {task_tag}  /  {event.get('status') or ''}")

        self.snapshot["terminal"] = entries


def stamp() -> str:
    return datetime.now().astimezone().strftime("%H:%M:%S")


def plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(item) for item in value]
    if hasattr(value, "model_dump"):
        return plain(value.model_dump(mode="json"))
    if is_dataclass(value):
        return plain(asdict(value))
    if hasattr(value, "value"):
        return plain(value.value)
    return str(value)


def model_dict(value: Any) -> dict[str, Any] | None:
    result = plain(value)
    return result if isinstance(result, dict) else None


def preview_text(value: Any, limit: int = 1000) -> str:
    """Bound a value for single-line terminal display, joining newlines with '  /  '."""
    text = str(value).strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "  /  ".join(part.strip() for part in text.split("\n") if part.strip())
    return text[:limit]


def append_terminal(terminal: list[dict[str, Any]], kind: str, text: str) -> list[dict[str, Any]]:
    """Append one terminal entry with deduplication and a hard cap of 80 entries."""
    text = preview_text(text)
    if not text:
        return terminal
    if terminal and terminal[-1].get("text") == text:
        return terminal
    return [*terminal, {"time": stamp(), "kind": kind, "text": text}][-80:]


def message_text(message: Any) -> str | None:
    """Extract displayable text from a LangChain message of any content shape."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if text:
                    parts.append(str(text))
            elif isinstance(block, str) and block:
                parts.append(block)
        return "\n".join(parts) if parts else None
    if isinstance(content, dict):
        text = content.get("text") or content.get("content")
        return str(text) if text else None
    if content:
        return str(content)
    return None


def message_kind(message: Any) -> str:
    """Map a LangChain message type to a terminal entry kind."""
    name = type(message).__name__.lower()
    if "tool" in name:
        return "error" if getattr(message, "status", None) == "error" else "success"
    if "ai" in name or "system" in name or "human" in name:
        return "system" if "ai" in name or "system" in name else "command"
    return "command"


def snapshot_from_state(state: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    runtime = model_dict(state.get("runtime_state")) or {}
    plan = model_dict(state.get("task_plan"))
    workflow = model_dict(state.get("execution_workflow"))
    decision_event = state.get("critic_runtime_event")
    decision = model_dict(decision_event)
    if decision:
        context = decision.pop("context", {}) or {}
        decision = {
            "event": decision.get("event"),
            "rationale": context.get("rationale", ""),
            "evidence": context.get("evidence", []),
        }

    terminal = list(previous.get("terminal", []))
    messages = state.get("messages", []) or []
    for message in messages[-3:]:
        text = message_text(message)
        if text:
            terminal = append_terminal(terminal, message_kind(message), text)

    previous_plan = previous.get("task_plan") or {}
    if plan and not previous_plan:
        tasks_count = len(plan.get("tasks", []) or [])
        terminal = append_terminal(terminal, "system", f"PLAN_MATERIALIZED  /  {plan.get('plan_id') or ''}  /  {tasks_count} task(s)")

    previous_decision = previous.get("decision") or {}
    if decision and previous_decision.get("event") != decision.get("event"):
        rationale = preview_text(decision.get("rationale", "") or "", limit=200)
        terminal = append_terminal(terminal, "system", f"DECISION  /  {decision.get('event') or ''}  /  {rationale or 'Critic evaluated runtime evidence.'}")

    active_memory = model_dict(state.get("active_memory")) or {}
    thread_memory = model_dict(state.get("thread_memory")) or {}
    persistent_memory = model_dict(state.get("persistent_memory")) or {}
    observation = model_dict(state.get("observation_input")) or {}
    processing = model_dict(state.get("runtime_processing_result")) or {}
    normalized = processing.get("normalized_result", {}) or {}
    execution_memory = plain(state.get("execution_memory", previous.get("execution_memory", [])))
    previous_flow = previous.get("concurrent_flow", {})
    live_by_id = {
        task.get("task_id"): task
        for task in previous_flow.get("tasks", [])
    }
    flow_tasks = []
    if plan:
        for task in plan.get("tasks", []):
            base_task = {
                "task_id": task.get("task_id"),
                "objective": task.get("objective", ""),
                "status": task.get("status", "pending"),
                "dependencies": task.get("dependencies", []),
                "blockers": task.get("blockers", []),
            }
            live = live_by_id.get(task.get("task_id"), {})
            merged = {**live, **base_task}
            for key in ("event", "error", "workflow", "started_at", "finished_at", "active"):
                if key in live:
                    merged[key] = live[key]
            flow_tasks.append(merged)

    latest_workflow = next(
        (
            task.get("workflow")
            for task in reversed(flow_tasks)
            if task.get("workflow")
        ),
        previous.get("execution_workflow"),
    )

    return {
        **previous,
        "mode": runtime.get("mode", previous.get("mode", "initializing")),
        "last_event": runtime.get("last_event", previous.get("last_event")),
        "iteration": runtime.get("iteration", previous.get("iteration", 0)),
        "goal": state.get("goal", previous.get("goal", "")),
        "task_plan": plan,
        "execution_workflow": workflow or latest_workflow,
        "terminal": terminal[-80:],
        "decision": decision or previous.get("decision"),
        "artifacts": plain(state.get("artifact_references", previous.get("artifacts", []))),
        "memory": {
            "active": memory_items(active_memory),
            "thread": memory_items(thread_memory),
            "persistent": memory_items(persistent_memory),
        },
        "observation": {
            "summary": state.get("observation_summary", previous.get("observation", {}).get("summary", "")),
            "important_information": state.get("observation_important_information", previous.get("observation", {}).get("important_information", "")),
            "conclusion": state.get("observation_conclusion", previous.get("observation", {}).get("conclusion", "")),
            "raw": observation.get("raw_result") or normalized.get("execution"),
        },
        "execution_memory": execution_memory,
        "concurrent_flow": {
            **previous_flow,
            "plan_id": plan.get("plan_id") if plan else previous_flow.get("plan_id"),
            "tasks": flow_tasks or previous_flow.get("tasks", []),
        },
    }


def memory_items(value: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for key, item in value.items():
        if item in (None, [], {}, ""):
            continue
        if isinstance(item, list):
            items.extend(str(entry) for entry in item[:10])
        elif isinstance(item, (str, int, float, bool)):
            items.append(f"{key}: {item}")
    return items[:20]


sessions: dict[str, TaskSession] = {}


_STAGE_MODE_MAP = {
    RuntimeStage.PLANNER: "planning",
    RuntimeStage.EXECUTOR: "executing",
    RuntimeStage.CRITIC: "reviewing",
    RuntimeStage.TERMINATE: "finished",
    RuntimeStage.ERROR: "error",
}

_KNOWN_MODES = set(_STAGE_MODE_MAP.values())


def stage_mode(state: dict[str, Any]) -> str | None:
    """Derive the UI mode from a graph state, independently of whether the
    yielded runtime_state carries an updated mode."""
    runtime = state.get("runtime_state")
    mode = None
    if runtime is not None:
        mode = getattr(runtime, "mode", None)
        if mode is None and isinstance(runtime, dict):
            mode = runtime.get("mode")
    if mode is not None:
        mode = str(getattr(mode, "value", mode))
        if mode in _KNOWN_MODES and mode != "initializing":
            return mode
    try:
        stage = runtime_stage_router(state)
    except Exception:
        return None
    return _STAGE_MODE_MAP.get(str(stage))


async def run_graph_async(session: TaskSession) -> None:
    session.running = True
    session.runner_loop = asyncio.get_running_loop()
    session.runner_task = asyncio.current_task()
    session.publish({"runtime_state": {"mode": "initializing"}}, "task_started")
    config = {"configurable": {"thread_id": session.task_id}}
    listener_token = set_stream_listener(session.thinking_update)
    concurrent_token = set_concurrent_event_listener(session.concurrent_update)
    cancel_token = set_cancel_check(session.cancel_requested.is_set)
    try:
        async for state in runtime_graph.astream(
            {"goal": session.goal},
            config=config,
            stream_mode="values",
        ):
            session.publish(state)
            sync = stage_mode(state)
            if sync and sync != "finished":
                session.sync_mode(sync)
        session.publish({"runtime_state": {"mode": "finished"}}, "goal_completed")
    except asyncio.CancelledError:
        session.cancelled()
    except Exception as error:  # The UI receives a structured failed runtime state.
        session.fail(error)
    finally:
        reset_stream_listener(listener_token)
        reset_concurrent_event_listener(concurrent_token)
        reset_cancel_check(cancel_token)
        session.running = False
        session.runner_task = None
        session.runner_loop = None
        with session.lock:
            session.snapshot["backend"] = {"connected": True, "running": False, "error": session.error}
            payload = dict(session.snapshot)
            subscribers = list(session.subscribers)
            loop = session.loop
        if loop is not None:
            for queue in subscribers:
                loop.call_soon_threadsafe(queue.put_nowait, payload)


def run_graph(session: TaskSession) -> None:
    """Run the async LangGraph lifecycle in its own worker thread."""

    asyncio.run(run_graph_async(session))


async def create_task(request: web.Request) -> web.Response:
    body = await request.json()
    goal = str(body.get("goal", "")).strip()
    if not goal:
        raise web.HTTPBadRequest(text="goal is required")
    session = TaskSession(goal)
    sessions[session.task_id] = session
    asyncio.create_task(asyncio.to_thread(run_graph, session))
    return web.json_response({"task_id": session.task_id, "snapshot": session.snapshot}, status=202)


async def get_snapshot(request: web.Request) -> web.Response:
    session = sessions.get(request.match_info["task_id"])
    if session is None:
        raise web.HTTPNotFound()
    return web.json_response(plain(session.snapshot))


async def terminate_task(request: web.Request) -> web.Response:
    session = sessions.get(request.match_info["task_id"])
    if session is None:
        raise web.HTTPNotFound()
    session.cancel_requested.set()
    with session.lock:
        if not session.running:
            return web.json_response({"status": "already_finished"})
        session.snapshot["last_event"] = "cancellation_requested"
        session.snapshot["backend"] = {"connected": True, "running": True, "error": None}
        session.snapshot["terminal"] = [
            *session.snapshot["terminal"],
            {"time": stamp(), "kind": "system", "text": "CANCELLATION_REQUESTED  /  Stopping agent run..."},
        ][-80:]
        payload = dict(session.snapshot)
        subscribers = list(session.subscribers)
        loop = session.loop
        runner_loop = session.runner_loop
        runner_task = session.runner_task
    if loop is not None:
        for queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
    if runner_loop is not None and runner_task is not None:
        runner_loop.call_soon_threadsafe(runner_task.cancel)
    return web.json_response({"status": "cancellation_requested"}, status=202)


async def events(request: web.Request) -> web.StreamResponse:
    session = sessions.get(request.match_info["task_id"])
    if session is None:
        raise web.HTTPNotFound()
    response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive", "Access-Control-Allow-Origin": "*"})
    await response.prepare(request)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    session.subscribers.add(queue)
    session.loop = asyncio.get_running_loop()
    try:
        await response.write(f"data: {json.dumps(plain(session.snapshot))}\n\n".encode())
        while True:
            payload = await queue.get()
            await response.write(f"data: {json.dumps(plain(payload))}\n\n".encode())
            if payload.get("mode") in {"finished", "error"}:
                break
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        session.subscribers.discard(queue)
    return response


@web.middleware
async def cors(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


def create_app() -> web.Application:
    app = web.Application(middlewares=[cors])
    app.router.add_post("/api/tasks", create_task)
    app.router.add_get("/api/tasks/{task_id}", get_snapshot)
    app.router.add_post("/api/tasks/{task_id}/terminate", terminate_task)
    app.router.add_get("/api/tasks/{task_id}/events", events)
    app.router.add_get("/health", lambda _request: web.json_response({"status": "ok"}))
    ui_dist = Path(__file__).parent / "ui" / "dist"
    if ui_dist.is_dir():
        app.router.add_static("/", ui_dist, show_index=True)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=HOST, port=PORT)
