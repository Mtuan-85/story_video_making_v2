"""Export project to Kdenlive (.kdenlive) + optional .srt.

Wraps `render/kdenlive_export.export_kdenlive` in a thread because
`xml.etree` writes the whole tree synchronously and the file might be large.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from loguru import logger as log

from render.kdenlive_export import export_kdenlive
from workers._async_thread import AsyncTaskWorker


class ExportKdenliveWorker(AsyncTaskWorker):
    """Export project to .kdenlive + .srt."""

    export_done = pyqtSignal(str, str)  # kdenlive_path, srt_path (empty if none)
    export_failed = pyqtSignal(str)  # reason

    def __init__(
        self,
        project,
        voice_mapping: dict | None,
        output_path: Path,
        also_srt: bool = True,
    ) -> None:
        super().__init__()
        self.project = project
        self.voice_mapping = voice_mapping
        self.output_path = Path(output_path)
        self.also_srt = also_srt

    async def _async_run(self) -> None:
        self.emit_log(f"Exporting Kdenlive XML → {self.output_path}")
        try:
            kpath, spath = await asyncio.to_thread(
                export_kdenlive,
                self.project,
                self.voice_mapping,
                self.output_path,
                self.also_srt,
            )
        except Exception as e:
            log.error(f"Kdenlive export failed: {e}")
            self.emit_log(f"❌ Export fail: {e}")
            self.export_failed.emit(str(e))
            return

        self.emit_log(f"✓ Kdenlive: {kpath}")
        if spath:
            self.emit_log(f"✓ Subtitles: {spath}")
        self.export_done.emit(str(kpath), str(spath) if spath else "")
