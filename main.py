"""Story Video Maker — PyQt6 entry point."""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger as log


def _bootstrap_diagnostics() -> Path:
    """Wire up crash diagnostics BEFORE any heavy imports.

    Three layers:
      1. faulthandler — captures C-level segfaults from cv2 / rembg / Qt
         to logs/faulthandler.log (file kept open for the process lifetime
         so the dump survives even if Python dies).
      2. loguru file sink — persists every DEBUG+ log line to
         logs/app.log, rotated at 10 MB, kept 7 days.
      3. excepthooks — unhandled exceptions on main thread AND worker
         threads get logged with full traceback.
    """
    logs_dir = Path(__file__).resolve().parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    fault_path = logs_dir / "faulthandler.log"
    fault_file = open(fault_path, "a", buffering=1, encoding="utf-8")
    fault_file.write(
        f"\n=== process start {datetime.now().isoformat(timespec='seconds')} "
        f"pid={os.getpid()} ===\n"
    )
    faulthandler.enable(file=fault_file, all_threads=True)

    app_log_path = logs_dir / "app.log"
    log.add(
        app_log_path,
        level="DEBUG",
        rotation="10 MB",
        retention=7,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {thread.name} | {name}:{function}:{line} | {message}",
    )

    def _excepthook(exc_type, exc, tb):
        log.opt(exception=(exc_type, exc, tb)).critical("Unhandled exception (main thread)")
        sys.__excepthook__(exc_type, exc, tb)

    def _thread_excepthook(args):
        log.opt(exception=(args.exc_type, args.exc_value, args.exc_traceback)).critical(
            f"Unhandled exception in thread {args.thread.name if args.thread else '?'}"
        )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook

    log.info(f"Diagnostics ready — app log: {app_log_path}, faulthandler: {fault_path}")
    return logs_dir


if __name__ == "__main__":
    _bootstrap_diagnostics()
    from ui.main_window import run
    run()
