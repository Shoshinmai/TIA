from __future__ import annotations

import json
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ConcurrentDebugSession:
    """
    Temporary debugging instrumentation for the concurrent executor.

    This does NOT execute tasks.

    It only creates per-task debug logs and records worker lifecycle
    events. Worker execution stays inside the backend service.

    Remove this helper after the async-IO migration debugging phase.
    """

    def __init__(
        self,
        *,
        plan_id: str,
        tasks,
    ) -> None:

        self.plan_id = plan_id

        self.run_id = f"{plan_id}-" f"{uuid.uuid4().hex[:8]}"

        self.root = Path(tempfile.gettempdir()) / "caso_concurrent_debug" / self.run_id

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._locks: dict[str, threading.Lock] = {}

        for task in tasks:
            self._locks[task.task_id] = threading.Lock()

    def log_path(
        self,
        task_id: str,
    ) -> Path:

        safe_task_id = task_id.replace("/", "_").replace("\\", "_").replace(":", "_")

        return self.root / f"{safe_task_id}.jsonl"

    def open_worker_tab(
        self,
        *,
        task_id: str,
    ) -> None:
        """Retained for compatibility with older debug callers."""
        return

    def open_tabs(
        self,
        *,
        tasks,
    ) -> None:

        for task in tasks:

            self.open_worker_tab(
                task_id=task.task_id,
            )

    def write(
        self,
        *,
        task_id: str,
        event: str,
        message: str = "",
        **metadata,
    ) -> None:

        payload = {
            "timestamp": (datetime.now(timezone.utc).isoformat()),
            "event": event,
            "task_id": task_id,
            "message": message,
            **metadata,
        }

        path = self.log_path(task_id)

        lock = self._locks.setdefault(
            task_id,
            threading.Lock(),
        )

        with lock:

            with path.open(
                "a",
                encoding="utf-8",
            ) as handle:

                handle.write(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

                handle.flush()

    def close_worker(
        self,
        *,
        task_id: str,
        status: str,
        error: str | None = None,
    ) -> None:

        self.write(
            task_id=task_id,
            event="DONE",
            message=(f"Worker completed with status={status}"),
            status=status,
            error=error,
        )
