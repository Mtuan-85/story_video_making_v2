"""Async worker base — runs coroutines on the main qasync event loop.

Patchright Page is bound to the loop that opened the CDP connection (qasync
loop on the main Qt thread). Running worker coroutines on a separate event
loop in a QThread silently hangs Patchright operations. This base schedules
work as an asyncio.Task on the main loop instead — UI stays responsive
because every `await` yields control back to Qt.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable

from loguru import logger as log
from PyQt6.QtCore import QObject, pyqtSignal


class AsyncTaskWorker(QObject):
    """QObject worker that schedules `_async_run()` on the main asyncio loop.

    Subclasses override `_async_run()`. Public API mirrors the previous
    QThread-based worker (start/isRunning/finished/log_message/request_stop)
    so call sites in the UI don't change.
    """

    finished = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._running: bool = False

    # Lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        loop = asyncio.get_event_loop()
        self._stop_event = asyncio.Event()
        self._running = True
        self._task = loop.create_task(self._wrapped_run())

    def isRunning(self) -> bool:
        return self._running

    def request_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    @property
    def stop_event(self) -> asyncio.Event:
        if self._stop_event is None:
            raise RuntimeError("stop_event chỉ truy cập được sau start()")
        return self._stop_event

    # Subclass hooks -----------------------------------------------------------

    async def _async_run(self) -> None:
        raise NotImplementedError

    async def run_with_stop(self, coro: Awaitable) -> object | None:
        """Race a coroutine against the stop event. Returns None if stopped."""
        stop_task = asyncio.create_task(self.stop_event.wait())
        work_task = asyncio.ensure_future(coro)
        try:
            done, _ = await asyncio.wait(
                {stop_task, work_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if work_task in done:
                stop_task.cancel()
                return work_task.result()
            work_task.cancel()
            try:
                await work_task
            except (asyncio.CancelledError, Exception):
                pass
            return None
        finally:
            if not stop_task.done():
                stop_task.cancel()

    # Helpers ------------------------------------------------------------------

    def emit_log(self, msg: str) -> None:
        log.info(msg)
        self.log_message.emit(msg)

    async def _wrapped_run(self) -> None:
        try:
            await self._async_run()
        except asyncio.CancelledError:
            self.emit_log("Worker cancelled")
        except Exception as e:
            log.exception(f"Worker {type(self).__name__} crashed: {e}")
            self.emit_log(f"❌ Lỗi worker: {e}")
        finally:
            self._running = False
            self._task = None
            self._stop_event = None
            self.finished.emit()


# Backwards-compat alias so subclasses don't need a sweep rename.
AsyncQThread = AsyncTaskWorker
