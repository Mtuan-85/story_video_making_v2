"""Export project to Kdenlive (.kdenlive) via Sprint 2 exporter.

Worker wraps `exporters.kdenlive_exporter.export_kdenlive_project` so the
heavy synchronous tree-walk + ffmpeg freeze-frame + PIL placeholder work
stays off the UI thread.

Inputs:
  - voice_matching_timeline.json (Sprint 1 output, under project voice/)
  - project root (for asset path resolution)
  - output_path (.kdenlive target)

Outputs (Sprint 2 spec):
  - {output}.kdenlive (MLT XML)
  - export_diagnostics.json (next to .kdenlive)
  - generated/freeze_frames/*.jpg
  - generated/placeholders/*.jpg
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from loguru import logger as log

from exporters.kdenlive_exporter import (
    POLICY_PLACEHOLDER,
    export_kdenlive_project,
)
from workers._async_thread import AsyncTaskWorker


class ExportKdenliveWorker(AsyncTaskWorker):
    """Run Sprint 2 Kdenlive export off the UI thread.

    Signals:
        export_done(kdenlive_path, diagnostics_path)
        export_failed(reason)
    """

    export_done = pyqtSignal(str, str)
    export_failed = pyqtSignal(str)

    def __init__(
        self,
        project,
        output_path: Path,
        timeline_json_path: Path | None = None,
        aspect_ratio: str = "16:9",
        missing_asset_policy: str = POLICY_PLACEHOLDER,
        strict_no_match: bool = False,
    ) -> None:
        super().__init__()
        self.project = project
        self.output_path = Path(output_path)
        self.aspect_ratio = aspect_ratio
        self.missing_asset_policy = missing_asset_policy
        self.strict_no_match = strict_no_match

        # Default: look for voice_matching_timeline.json under project voice/
        if timeline_json_path is None:
            timeline_json_path = self.project.paths.root / "voice" / "voice_matching_timeline.json"
        self.timeline_json_path = Path(timeline_json_path)

    async def _async_run(self) -> None:
        self.emit_log(f"Kdenlive export → {self.output_path}")

        if not self.timeline_json_path.exists():
            msg = (
                f"voice_matching_timeline.json không tồn tại: {self.timeline_json_path}. "
                f"Chạy voice alignment trước."
            )
            self.emit_log(f"❌ {msg}")
            self.export_failed.emit(msg)
            return

        try:
            result = await asyncio.to_thread(
                export_kdenlive_project,
                self.timeline_json_path,
                self.output_path,
                self.project.paths.root,
                self.output_path.stem,                       # title
                self.aspect_ratio,
                self.missing_asset_policy,
                self.strict_no_match,
            )
        except Exception as e:
            log.exception("Kdenlive export crashed")
            self.emit_log(f"❌ Export crash: {e}")
            self.export_failed.emit(str(e))
            return

        if not result.ok:
            reason = "; ".join(result.errors[:3]) or "unknown export failure"
            self.emit_log(f"❌ Export fail: {reason}")
            self.export_failed.emit(reason)
            return

        if result.warnings:
            self.emit_log(f"⚠ {len(result.warnings)} warning(s) — see diagnostics")
            for w in result.warnings[:5]:
                self.emit_log(f"   • {w}")

        kpath = str(result.kdenlive_path) if result.kdenlive_path else ""
        dpath = str(result.diagnostics_path) if result.diagnostics_path else ""
        self.emit_log(f"✓ Kdenlive: {result.kdenlive_path}")
        if result.diagnostics_path:
            self.emit_log(f"✓ Diagnostics: {result.diagnostics_path}")
        self.export_done.emit(kpath, dpath)
