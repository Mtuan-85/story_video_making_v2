from __future__ import annotations

import asyncio
import sys

import qasync
from dotenv import load_dotenv
from loguru import logger
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    load_dotenv()
    import sys as _sys
    logger.remove()
    logger.add(_sys.stderr, level="DEBUG")
    logger.info("Khởi động Grok Automation")

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        return loop.run_forever() or 0


if __name__ == "__main__":
    sys.exit(main())
