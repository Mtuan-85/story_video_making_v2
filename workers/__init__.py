"""QThread workers — bridge UI events to async engine calls.

Workers don't touch the UI directly; they emit pyqtSignals consumed by the
main window. Each worker owns its own asyncio event loop (created in run())
because Patchright is async-only and Qt's main loop is not asyncio-driven.
"""
