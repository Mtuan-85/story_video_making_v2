"""Async worker — runs voice alignment on the qasync main loop.

Whisper + Claude CLI are blocking subprocesses, so we wrap them in
`asyncio.to_thread` to keep the UI responsive.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from PyQt6.QtCore import pyqtSignal

from core.voice_mapping import VoiceFile, VoiceMapping
from voice.voice_aligner import align_voice_file, AlignResult
from workers._async_thread import AsyncTaskWorker


class VoiceAlignWorker(AsyncTaskWorker):
    """Aligns a list of voice files into a single VoiceMapping.

    Signals:
        progress(filename, current_step, total_steps)
        file_done(filename, VoiceFile)
        all_done(VoiceMapping)
        failed(filename, reason)
    """

    progress = pyqtSignal(str, int, int)
    file_done = pyqtSignal(str, object)
    all_done = pyqtSignal(object)
    failed = pyqtSignal(str, str)

    def __init__(
        self,
        voice_files: list[Path],
        scene_assignments: dict[str, list[str]],
        scenes: list[dict[str, Any]],
        work_dir: Path,
        project_root: Path,
        silent_scenes: list[str] | None = None,
        whisper_model: str = "base",
        language: str = "en",
    ) -> None:
        super().__init__()
        self.voice_files = [Path(p) for p in voice_files]
        self.scene_assignments = scene_assignments
        self.scenes = scenes
        self.work_dir = Path(work_dir)
        self.project_root = Path(project_root)
        self.silent_scenes = list(silent_scenes or [])
        self.whisper_model = whisper_model
        self.language = language

    async def _async_run(self) -> None:
        results: list[VoiceFile] = []
        all_silent: set[str] = set(self.silent_scenes)
        all_warnings: list[str] = []
        total = len(self.voice_files)

        for i, voice_path in enumerate(self.voice_files, start=1):
            if self.stop_event.is_set():
                self.emit_log("Đã hủy alignment")
                return

            self.emit_log(f"[{i}/{total}] Aligning {voice_path.name}...")
            self.progress.emit(voice_path.name, 1, 3)

            scene_ids_for_file = self.scene_assignments.get(voice_path.name, [])
            scenes_for_file = [s for s in self.scenes if s["id"] in scene_ids_for_file]
            if not scenes_for_file:
                self.emit_log(f"⚠ Không có scenes nào assigned cho {voice_path.name}")
                continue

            try:
                align_res: AlignResult = await asyncio.to_thread(
                    align_voice_file,
                    voice_path,
                    scenes_for_file,
                    self.work_dir,
                    self.project_root,
                    self.whisper_model,
                    self.language,
                )
            except Exception as e:
                self.emit_log(f"❌ {voice_path.name}: {e}")
                self.failed.emit(voice_path.name, str(e))
                continue

            voice_file = align_res.voice_file
            all_silent.update(align_res.silent_scenes)
            all_warnings.extend(align_res.warnings)

            self.progress.emit(voice_path.name, 3, 3)
            self.file_done.emit(voice_path.name, voice_file)
            results.append(voice_file)
            self.emit_log(
                f"✓ {voice_path.name} aligned: {len(voice_file.scenes)} scenes, "
                f"{len(voice_file.phases)} phases"
            )
            for w in align_res.warnings:
                self.emit_log(f"⚠ {w}")

        mapping = VoiceMapping(
            voice_files=results,
            silent_scenes=sorted(all_silent),
            warnings=all_warnings,
        )
        self.all_done.emit(mapping)
