from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "CASO temporary concurrent worker PowerShell monitor."
        )
    )

    parser.add_argument(
        "--log",
        required=True,
        help="Path to the worker JSONL debug log.",
    )

    parser.add_argument(
        "--task-id",
        required=True,
        help="Task ID displayed by this monitor.",
    )

    parser.add_argument(
        "--poll",
        type=float,
        default=0.10,
        help="Polling interval in seconds.",
    )

    return parser.parse_args()


def format_event(event: dict) -> str:
    event_type = event.get(
        "event",
        "UNKNOWN",
    )

    task_id = event.get(
        "task_id",
        "",
    )

    message = event.get(
        "message",
        "",
    )

    timestamp = event.get(
        "timestamp",
        "",
    )

    if message:
        return (
            f"[{timestamp}] "
            f"{event_type:<14} "
            f"{message}"
        )

    return (
        f"[{timestamp}] "
        f"{event_type:<14} "
        f"task={task_id}"
    )


def print_header(
    *,
    task_id: str,
    log_path: Path,
) -> None:

    print()
    print("=" * 80)
    print(
        f" CASO CONCURRENT WORKER MONITOR | {task_id}"
    )
    print("=" * 80)
    print(
        f"LOG: {log_path}"
    )
    print()
    print(
        "This window is a DEBUG MONITOR only."
    )
    print(
        "The real worker is running inside the original "
        "Python process."
    )
    print()
    print("-" * 80)
    print(
        "WAITING FOR WORKER EVENTS..."
    )
    print("-" * 80)
    print(
        flush=True
    )


def wait_for_log_event(
    *,
    log_path: Path,
    position: int,
    poll_interval: float,
) -> tuple[int, bool]:

    finished = False

    if not log_path.exists():

        time.sleep(
            poll_interval
        )

        return position, finished

    with log_path.open(
        "r",
        encoding="utf-8",
    ) as handle:

        # Continue from the point already displayed.
        handle.seek(position)

        while True:

            line = handle.readline()

            if not line:
                break

            position = handle.tell()

            line = line.strip()

            if not line:
                continue

            try:

                event = json.loads(
                    line
                )

            except json.JSONDecodeError:

                print(
                    f"[RAW] {line}",
                    flush=True,
                )

                continue

            print(
                format_event(event),
                flush=True,
            )

            if event.get(
                "event"
            ) == "DONE":

                finished = True

    return position, finished


def main() -> None:

    args = parse_args()

    log_path = Path(
        args.log
    )

    print_header(
        task_id=args.task_id,
        log_path=log_path,
    )

    position = 0

    while True:

        position, finished = (
            wait_for_log_event(
                log_path=log_path,
                position=position,
                poll_interval=args.poll,
            )
        )

        if finished:

            print()
            print("=" * 80)
            print(
                f" WORKER FINISHED | {args.task_id}"
            )
            print("=" * 80)
            print()
            print(
                "The real worker has finished."
            )
            print(
                "The original PowerShell process is now "
                "continuing its execution flow."
            )
            print()
            print(
                "This debug window will remain open."
            )
            print(
                "Press ENTER to close it."
            )
            print(
                flush=True
            )

            try:
                input()

            except EOFError:
                pass

            return

        time.sleep(
            args.poll
        )


if __name__ == "__main__":
    main()