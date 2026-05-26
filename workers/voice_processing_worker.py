"""Workers for post-Process-Voice source stages."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from loguru import logger as log

from core.project import Project
from voice.master_whisper import transcribe_master_audio
from voice.voice_enhancer import (
    apply_voice_pacing_operations,
    build_voice_pacing_operations,
    load_whisper_words,
    save_voice_pacing_plan,
)
from workers._async_thread import AsyncTaskWorker
from workers.two_level_match_worker import save_whisper_words_for_source


class VoiceEnhanceWorker(AsyncTaskWorker):
    failed = pyqtSignal(str)
    done = pyqtSignal(str, str)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project

    async def _async_run(self) -> None:
        paths = self.project.paths
        raw_master = paths.master_voice_raw_wav
        raw_words = paths.whisper_words_raw_json
        enhanced_master = paths.master_voice_enhanced_wav
        if not raw_master.exists():
            self.failed.emit(f"Thiếu raw master voice: {raw_master}")
            return
        if not raw_words.exists():
            self.failed.emit(f"Thiếu raw whisper words: {raw_words}")
            return

        self.emit_log("▶ Auto Enhance Voice: analyze raw Whisper words...")
        try:
            words = await asyncio.to_thread(load_whisper_words, raw_words)
            plan = build_voice_pacing_operations(raw_master, enhanced_master, words)
            await asyncio.to_thread(save_voice_pacing_plan, plan, paths.voice_pacing_operations_json)
            report = await asyncio.to_thread(
                apply_voice_pacing_operations,
                raw_master,
                enhanced_master,
                plan,
            )
            paths.voice_enhance_report_json.parent.mkdir(parents=True, exist_ok=True)
            paths.voice_enhance_report_json.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.exception("Auto Enhance Voice failed")
            self.failed.emit(str(e))
            return

        self.emit_log(
            f"✓ Enhanced voice: {enhanced_master.name} "
            f"({len(plan.get('operations', []))} operation(s))"
        )
        self.done.emit(str(enhanced_master), str(paths.voice_enhance_report_json))


class VoiceWhisperWorker(AsyncTaskWorker):
    failed = pyqtSignal(str)
    done = pyqtSignal(str, str)

    def __init__(
        self,
        project: Project,
        source: str,
        whisper_model: str = "base",
    ) -> None:
        super().__init__()
        self.project = project
        self.source = source
        self.whisper_model = whisper_model

    async def _async_run(self) -> None:
        paths = self.project.paths
        if self.source == "enhance":
            master = paths.master_voice_enhanced_wav
        else:
            master = paths.master_voice_raw_wav
            self.source = "raw"
        if not master.exists():
            self.failed.emit(f"Thiếu master voice cho source {self.source}: {master}")
            return

        language = self.project.scenes_json.meta.language or "en"
        self.emit_log(
            f"▶ Whisper {self.source}: {master.name} "
            f"(model={self.whisper_model}, lang={language})"
        )
        try:
            words = await transcribe_master_audio(
                master_path=master,
                language=language,
                model_name=self.whisper_model,
            )
            words_path = await asyncio.to_thread(
                save_whisper_words_for_source,
                self.project,
                self.source,
                master,
                words,
            )
        except Exception as e:
            log.exception("Voice Whisper failed")
            self.failed.emit(str(e))
            return
        self.emit_log(f"✓ Whisper {self.source}: {len(words)} words → {words_path.name}")
        self.done.emit(self.source, str(words_path))

