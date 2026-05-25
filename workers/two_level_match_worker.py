"""Sprint 1 two-level voice matching worker.

Replaces the legacy `VoiceAlignWorker` (which globally fuzzy-matched across
all .mp3/.wav files in voice/). The new pipeline expects per-beat MP3
files + an S5 beat JSON authored by the user.

Pipeline (per sprint_1_two_level_voice_matching_spec.md):
  1. Load + validate {stem}_S5.json against {stem}_edited.json
  2. ffprobe each beat MP3 → exact beat timeline
  3. ffmpeg concat beats + synthetic silence → master_voice.wav
  4. Whisper transcribe master_voice.wav once → global word timestamps
  5. Per-beat scene matching (flexible window, no_match keeps voiced)
  6. Save voice_matching_timeline.json + voice_matching_diagnostics.json

Stages emit progress logs so the user can follow along.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from loguru import logger as log

from core.project import Project
from voice.beat_timeline import build_beat_timeline
from voice.master_audio_builder import build_master_audio
from voice.master_whisper import transcribe_master_audio
from voice.s5_loader import load_and_validate_s5
from voice.timeline_builder import build_timeline, save_outputs
from workers._async_thread import AsyncTaskWorker


class TwoLevelMatchWorker(AsyncTaskWorker):
    """Build voice_matching_timeline.json from S5 beats + per-beat MP3s.

    Signals:
        log_message(text)
        failed(stage, msg)
        done(timeline_path, diagnostics_path)
    """

    log_message = pyqtSignal(str)
    failed = pyqtSignal(str, str)
    done = pyqtSignal(str, str)

    def __init__(
        self,
        project: Project,
        whisper_model: str = "base",
        skip_master_rebuild_if_exists: bool = True,
    ) -> None:
        super().__init__()
        self.project = project
        self.whisper_model = whisper_model
        self.skip_master_rebuild_if_exists = skip_master_rebuild_if_exists
        self._generated_paths: list[Path] = []

    def request_stop(self) -> None:
        super().request_stop()
        self.emit_log("Process Voice stop requested; cleanup will run after current step")

    def _stop_requested(self) -> bool:
        try:
            return self.stop_event.is_set()
        except RuntimeError:
            return False

    def _cleanup_generated_outputs(self) -> None:
        for path in self._generated_paths:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

    def _cancel_if_stopped(self, stage: str) -> bool:
        if not self._stop_requested():
            return False
        self._cleanup_generated_outputs()
        self._fail(stage, "user_stopped; generated voice matching outputs removed")
        return True

    async def _async_run(self) -> None:
        paths = self.project.paths

        # ---- Step 1: S5 + scenes ----
        self.emit_log(f"▶ Step 1/6: Load & validate {paths.s5_beats_json.name}")
        s5_result = await asyncio.to_thread(
            load_and_validate_s5,
            paths.s5_beats_json,
            paths.scenes_edited,
            paths.voice_dir,
        )
        if not s5_result.ok:
            self._fail("s5_load", "; ".join(s5_result.errors[:3]))
            return
        if self._cancel_if_stopped("s5_load"):
            return
        beats = s5_result.beats
        self.emit_log(
            f"  ✓ {len(beats)} beats, {s5_result.ref_count} scene refs, "
            f"{len(s5_result.warnings)} warning(s)"
        )
        for w in s5_result.warnings[:5]:
            self.emit_log(f"  ⚠ {w}")

        # ---- Step 2: Beat timeline (ffprobe) ----
        self.emit_log(f"▶ Step 2/6: ffprobe per beat → exact beat timeline")
        bt_result = await asyncio.to_thread(build_beat_timeline, beats)
        if not bt_result.ok:
            self._fail("beat_timeline", "; ".join(bt_result.errors[:3]))
            return
        if self._cancel_if_stopped("beat_timeline"):
            return
        timed_beats = bt_result.beats
        self.emit_log(
            f"  ✓ total duration {bt_result.total_duration:.2f}s "
            f"(voice {sum(b.measured_duration for b in timed_beats):.2f}s + "
            f"pauses {sum(b.pause_after_sec for b in timed_beats):.2f}s)"
        )

        # ---- Step 3: Build master_voice.wav ----
        master_path = paths.master_voice_wav
        if self.skip_master_rebuild_if_exists and master_path.exists():
            self.emit_log(
                f"▶ Step 3/6: master_voice.wav exists "
                f"({master_path.stat().st_size / 1e6:.1f} MB) — skipping rebuild"
            )
        else:
            self.emit_log(f"▶ Step 3/6: Concat beats + synthetic silence → {master_path.name}")
            ma_result = await asyncio.to_thread(
                build_master_audio, timed_beats, master_path,
            )
            if not ma_result.ok:
                self._fail("master_audio", ma_result.error or "unknown")
                return
            if master_path.exists():
                self._generated_paths.append(master_path)
            self.emit_log(
                f"  ✓ {ma_result.measured_duration:.2f}s "
                f"(drift {ma_result.delta_sec:+.3f}s, "
                f"{master_path.stat().st_size / 1e6:.1f} MB)"
            )
        if self._cancel_if_stopped("master_audio"):
            return

        # ---- Step 4: Whisper on master ----
        language = self.project.scenes_json.meta.language or "en"
        self.emit_log(
            f"▶ Step 4/6: Whisper transcribe {master_path.name} "
            f"(model={self.whisper_model}, lang={language}) — 4-8 phút..."
        )
        try:
            whisper_words = await transcribe_master_audio(
                master_path=master_path,
                language=language,
                model_name=self.whisper_model,
            )
        except Exception as e:
            log.exception("Whisper master transcription failed")
            self._fail("whisper", str(e))
            return
        if not whisper_words:
            self._fail("whisper", "Whisper produced no words")
            return
        if self._cancel_if_stopped("whisper"):
            return
        self.emit_log(f"  ✓ {len(whisper_words)} words on master timeline")

        # ---- Step 5: Two-level matcher ----
        self.emit_log(f"▶ Step 5/6: Per-beat scene matching (flexible fuzzy)")
        try:
            scenes_data = json.loads(paths.scenes_edited.read_text(encoding="utf-8"))
            scenes_list = scenes_data["scenes"] if isinstance(scenes_data, dict) else scenes_data
            scenes_by_id = {s["id"]: s for s in scenes_list}
        except Exception as e:
            self._fail("scenes_load", f"Cannot read scenes_edited.json: {e}")
            return
        if self._cancel_if_stopped("scenes_load"):
            return

        aspect = self.project.scenes_json.meta.aspect_ratio
        canvas_w, canvas_h = (1080, 1920) if aspect == "9:16" else (1920, 1080)

        try:
            result = await asyncio.to_thread(
                build_timeline,
                timed_beats,
                scenes_by_id,
                whisper_words,
                master_path,
                self.project.scenes_json.meta.title or paths.stem,
                30,           # fps
                canvas_w,
                canvas_h,
            )
        except Exception as e:
            log.exception("Two-level matcher crashed")
            self._fail("matcher", str(e))
            return

        if not result.ok:
            self._fail("matcher", "; ".join(result.errors[:3]))
            return
        if self._cancel_if_stopped("matcher"):
            return

        s = result.diagnostics["summary"]
        self.emit_log(
            f"  ✓ {s['voiced_scenes']} voiced (unmatched {s['unmatched_voiced_scenes']}), "
            f"{s['silent_scenes']} silent, {s['beat_pauses']} pauses"
        )
        for w in result.warnings[:5]:
            self.emit_log(f"  ⚠ {w}")

        # ---- Step 6: Save outputs ----
        timeline_path = paths.voice_matching_timeline_json
        diag_path = paths.voice_matching_diagnostics_json
        self.emit_log(f"▶ Step 6/6: Save {timeline_path.name} + diagnostics")
        try:
            await asyncio.to_thread(
                save_outputs, result, timeline_path, diag_path,
            )
        except Exception as e:
            self._fail("save", str(e))
            return
        self._generated_paths.extend([timeline_path, diag_path])
        if self._cancel_if_stopped("save"):
            return

        self.emit_log(
            f"✓ DONE. Timeline → {timeline_path.name} "
            f"(duration {s['total_duration']:.2f}s, {s['scenes']} scenes, "
            f"{s['beat_pauses']} pauses)"
        )
        self.done.emit(str(timeline_path), str(diag_path))

    def _fail(self, stage: str, msg: str) -> None:
        self.emit_log(f"❌ {stage}: {msg}")
        self.failed.emit(stage, msg)
