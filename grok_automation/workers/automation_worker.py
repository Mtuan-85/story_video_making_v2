from __future__ import annotations

import asyncio
from typing import Any, Coroutine

from loguru import logger


def determine_flow(settings: dict) -> str:
    """Auto-pick flow key based on type + whether any prompt has a ref."""
    type_ = settings.get("type", "image")
    prompts = settings.get("prompts", [])
    has_any_ref = any(p.get("ref") for p in prompts)

    if type_ == "image":
        return "image_to_image" if has_any_ref else "text_to_image"
    return "image_to_video" if has_any_ref else "text_to_video"


def get_target_count(settings: dict) -> int:
    """Quality=4, Speed=8, Video=1."""
    if settings.get("type") != "image":
        return 1
    return 4 if settings.get("quality") == "quality" else 8


def validate_before_start(settings: dict) -> tuple[bool, str]:
    """Returns (is_valid, error_message_vi)."""
    if not settings.get("project_name"):
        return False, "Project name không được rỗng"

    prompts = settings.get("prompts") or []
    if not prompts:
        return False, "Chưa load prompts JSON"

    prompts_with_ref = [
        (i + 1, p) for i, p in enumerate(prompts) if p.get("ref")
    ]
    if prompts_with_ref:
        if not settings.get("ref_folder"):
            return False, "Có prompts cần ref nhưng chưa chọn ref folder"
        ref_cache = settings.get("ref_cache") or {}
        missing = [
            f"#{idx}: '{p['ref']}'"
            for idx, p in prompts_with_ref
            if p["ref"] not in ref_cache
        ]
        if missing:
            return False, f"Thiếu ref files: {', '.join(missing)}"

    return True, ""


class AutomationWorker:
    """Bridge between Qt UI and asyncio coroutines via qasync.

    Phase 1 only needs fire-and-forget scheduling for connect/list/select/disconnect.
    Heavier orchestration (run loop, pause/stop) lands in Phase 2+.
    """

    def __init__(self) -> None:
        pass

    def run(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        loop = asyncio.get_event_loop()
        task = loop.create_task(coro)
        task.add_done_callback(self._log_exception)
        return task

    def run_blocking(self, coro: Coroutine[Any, Any, Any]) -> Any:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)

    @staticmethod
    def _log_exception(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.exception(f"Worker task failed: {exc}")
