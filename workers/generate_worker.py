from __future__ import annotations

import argparse
import asyncio
import time
from typing import Sequence

from workers.task_contract import (
    EXIT_FLOW_FAILED,
    EXIT_SUCCESS,
    GenerateTask,
    event_line,
    marker_line,
)


def _print_marker(marker: str, payload: dict[str, object]) -> None:
    print(marker_line(marker, payload), flush=True)


def _print_event(event_type: str, **payload: object) -> None:
    print(event_line(event_type, **payload), flush=True)


def _asset_for_task_type(task_type: str) -> str:
    if task_type.endswith("_video"):
        return "video"
    return "image"


def run(task: GenerateTask, *, dry_run: bool) -> int:
    started_at = time.monotonic()
    _print_marker(
        "TASK START",
        {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "provider": task.provider,
            "model": task.model,
        },
    )

    if not dry_run:
        if task.provider != "grok":
            _print_marker(
                "TASK FAILED",
                {
                    "task_id": task.task_id,
                    "reason": f"provider not implemented: {task.provider}",
                    "code": EXIT_FLOW_FAILED,
                },
            )
            return EXIT_FLOW_FAILED

        if task.task_type not in ("batch_image", "single_image"):
            _print_marker(
                "TASK FAILED",
                {
                    "task_id": task.task_id,
                    "reason": f"task_type not implemented: {task.task_type}",
                    "code": EXIT_FLOW_FAILED,
                },
            )
            return EXIT_FLOW_FAILED

        try:
            from engines.grok.image_worker_flow import run_grok_image_task

            success, total = asyncio.run(run_grok_image_task(task))
        except Exception as exc:
            _print_marker(
                "TASK FAILED",
                {
                    "task_id": task.task_id,
                    "reason": str(exc),
                    "code": EXIT_FLOW_FAILED,
                },
            )
            return EXIT_FLOW_FAILED

        _print_marker(
            "TASK DONE",
            {
                "success": success,
                "total": total,
                "duration_sec": round(time.monotonic() - started_at, 3),
            },
        )
        return EXIT_SUCCESS if success == total else EXIT_FLOW_FAILED

    asset = _asset_for_task_type(task.task_type)
    for scene_id in task.scene_ids:
        _print_event("scene_started", scene_id=scene_id, asset=asset)
        _print_event(
            "scene_done",
            scene_id=scene_id,
            asset=asset,
            path="",
            duration_sec=0,
        )

    _print_marker(
        "TASK DONE",
        {
            "success": len(task.scene_ids),
            "total": len(task.scene_ids),
            "duration_sec": round(time.monotonic() - started_at, 3),
        },
    )
    return EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    task = GenerateTask.load(args.task)
    return run(task, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
