"""Retry-with-kill-and-relaunch wrapper used by all gen workers.

Single recovery primitive: any exception from the gen factory triggers
`connection.kill_and_relaunch_brave()` then a retry. Max 3 attempts.
On exhaust → return needs_user_decision=True (worker decides what to do).

Cancellation (asyncio.CancelledError) propagates through — never relaunches.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger as log


GenFactory = Callable[[], Awaitable[Any]]
RefreshPage = Callable[[], None]
LogCb = Callable[[str], None]


async def run_with_retry(
    *,
    scene_id: str,
    gen_factory: GenFactory,
    connection,
    project_root: Path,
    refresh_page: RefreshPage,
    log_cb: LogCb,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Run gen_factory up to max_attempts; kill+relaunch Brave between fails.

    Returns:
        {"ok": True, "result": <gen result>, "attempts": int}
      or
        {"ok": False, "needs_user_decision": True, "last_error": str, "attempts": int}
    """
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        log_cb(f"[ATTEMPT {attempt}/{max_attempts}] {scene_id}")
        try:
            result = await gen_factory()
            return {"ok": True, "result": result, "attempts": attempt}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            last_err = e
            log_cb(f"[FAIL {attempt}] {scene_id}: {e}")

        if attempt < max_attempts:
            try:
                log_cb("[BRAVE] kill+relaunch...")
                await connection.kill_and_relaunch_brave(project_root=project_root)
                refresh_page()
            except asyncio.CancelledError:
                raise
            except Exception as relaunch_err:
                log_cb(f"[RELAUNCH FAIL] {relaunch_err}")
                # next attempt likely fails too — that's OK, we'll exhaust and
                # surface needs_user_decision.

    log.error(f"[MAX_RETRY] {scene_id} failed after {max_attempts} attempts (last={last_err})")
    return {
        "ok": False,
        "needs_user_decision": True,
        "last_error": str(last_err) if last_err else "unknown",
        "attempts": max_attempts,
    }
