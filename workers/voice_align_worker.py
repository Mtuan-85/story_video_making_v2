"""Async worker — runs Plan D voice alignment on the qasync main loop.

Calls `voice.voice_aligner.align_voice_to_scenes` (whisper + deterministic
fuzzy + LLM fallback) and emits the resulting v4.0 `VoiceMapping`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import pyqtSignal

from core.voice_mapping import VoiceMapping
from voice.voice_aligner import align_voice_to_scenes
from workers._async_thread import AsyncTaskWorker


class VoiceAlignWorker(AsyncTaskWorker):
    """Aligns the voice folder against scenes (Plan D, single pass).

    Signals:
        progress(filename, current_step, total_steps)
        all_done(VoiceMapping)
        failed(filename, reason)
    """

    progress = pyqtSignal(str, int, int)
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
        self.scene_assignments = scene_assignments  # kept for legacy callers; Plan D ignores
        self.scenes = scenes
        self.work_dir = Path(work_dir)
        self.project_root = Path(project_root)
        self.user_silent_scenes = set(silent_scenes or [])
        self.whisper_model = whisper_model
        self.language = language

    async def _async_run(self) -> None:
        if not self.voice_files:
            self.failed.emit("", "no voice files")
            return

        voice_dir = self.voice_files[0].parent
        for vf in self.voice_files:
            if vf.parent != voice_dir:
                self.failed.emit(vf.name, f"all voice files must live in {voice_dir}")
                return

        # User-flagged silent scenes: drop story_en so Plan D marks them silent.
        scenes_for_align: list[dict[str, Any]] = []
        for s in self.scenes:
            sc = dict(s)
            if sc["id"] in self.user_silent_scenes:
                sc["story_en"] = ""
                sc["story_vi"] = ""
            scenes_for_align.append(sc)

        self.emit_log(
            f"▶ Plan D align: {len(self.voice_files)} file(s), "
            f"{len(scenes_for_align)} scene(s), model={self.whisper_model}"
        )
        self.progress.emit(voice_dir.name, 1, 3)

        try:
            mapping_dict = await align_voice_to_scenes(
                scenes=scenes_for_align,
                voice_dir=voice_dir,
                output_dir=self.project_root,
                whisper_model=self.whisper_model,
                language=self.language,
            )
        except Exception as e:
            self.emit_log(f"❌ alignment failed: {e}")
            self.failed.emit(voice_dir.name, str(e))
            return

        self.progress.emit(voice_dir.name, 3, 3)

        try:
            mapping = VoiceMapping.model_validate(mapping_dict)
        except Exception as e:
            self.emit_log(f"❌ voice_mapping schema invalid: {e}")
            self.failed.emit(voice_dir.name, f"schema: {e}")
            return

        stats = mapping.stats
        self.emit_log(
            f"✓ Plan D done: {stats.total_scenes} scenes, "
            f"deterministic={stats.deterministic_pass}, "
            f"llm_fallback={stats.llm_fallback_count}, silent={stats.silent}"
        )
        self.all_done.emit(mapping)
