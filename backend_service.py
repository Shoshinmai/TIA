from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from aiohttp import web

from llm.llmclient import reset_stream_listener, set_stream_listener
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
            "backend": {"connected": True, "running": False, "error": None},
        }
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.running = False
        self.error: str | None = None
        self.lock = threading.Lock()

    def publish(self, state: dict[str, Any], event: str | None = None) -> None:
        with self.lock:
            self.snapshot = snapshot_from_state(state, self.snapshot)
            self.snapshot["backend"] = {"connected": True, "running": True, "error": None}
            if event:
                self.snapshot["last_event"] = event
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
            payload = dict(self.snapshot)
            subscribers = list(self.subscribers)
            loop = self.loop
        if loop is not None:
            for queue in subscribers:
                loop.call_soon_threadsafe(queue.put_nowait, payload)


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
        content = getattr(message, "content", None)
        if content and isinstance(content, str):
            entry = {"time": stamp(), "kind": "command", "text": content[:2000]}
            if not terminal or terminal[-1].get("text") != entry["text"]:
                terminal.append(entry)

    active_memory = model_dict(state.get("active_memory")) or {}
    thread_memory = model_dict(state.get("thread_memory")) or {}
    persistent_memory = model_dict(state.get("persistent_memory")) or {}
    observation = model_dict(state.get("observation_input")) or {}
    processing = model_dict(state.get("runtime_processing_result")) or {}
    normalized = processing.get("normalized_result", {}) or {}
    execution_memory = plain(state.get("execution_memory", previous.get("execution_memory", [])))

    return {
        **previous,
        "mode": runtime.get("mode", previous.get("mode", "initializing")),
        "last_event": runtime.get("last_event", previous.get("last_event")),
        "iteration": runtime.get("iteration", previous.get("iteration", 0)),
        "goal": state.get("goal", previous.get("goal", "")),
        "task_plan": plan,
        "execution_workflow": workflow,
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


def run_graph(session: TaskSession) -> None:
    session.running = True
    session.publish({"runtime_state": {"mode": "initializing"}}, "task_started")
    config = {"configurable": {"thread_id": session.task_id}}
    listener_token = set_stream_listener(session.thinking_update)
    try:
        for state in runtime_graph.stream(
            {"goal": session.goal},
            config=config,
            stream_mode="values",
        ):
            session.publish(state)
        session.publish({"runtime_state": {"mode": "finished"}}, "goal_completed")
    except Exception as error:  # The UI receives a structured failed runtime state.
        session.fail(error)
    finally:
        reset_stream_listener(listener_token)
        session.running = False
        session.snapshot["backend"] = {"connected": True, "running": False, "error": session.error}


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
    app.router.add_get("/api/tasks/{task_id}/events", events)
    app.router.add_get("/health", lambda _request: web.json_response({"status": "ok"}))
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=HOST, port=PORT)
