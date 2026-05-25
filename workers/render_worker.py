"""Native timeline render pipeline: visual timeline → master voice final mux."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from core.voice_mapping import VoiceMapping
from render.bgm_mixer import (
    burn_subtitle_mix_master_audio_bgm,
    pick_bgm_files,
)
from render.timeline_visual import render_timeline_visuals
from voice.ass_generator import generate_final_ass
from workers._async_thread import AsyncTaskWorker


def _visual_state_key(visual_type: str) -> str:
    """Map Scene.visual_type → key in state.scenes[id] dict."""
    return "image" if visual_type == "Image" else "video"


def _resolve_path(project: Project, rel_or_abs: str | None) -> Path | None:
    if not rel_or_abs:
        return None
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = project.paths.root / p
    return p if p.exists() else None


class RenderWorker(AsyncTaskWorker):
    """Native timeline render pipeline.

    Requires voice_matching_timeline.json + master_voice.wav. Audio stays as one
    continuous master track; only visuals are segmented by timeline.
    """

    scene_started = pyqtSignal(str)
    scene_done = pyqtSignal(str)
    scene_failed = pyqtSignal(str, str)
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(str)
    finished_fail = pyqtSignal(str)

    def __init__(
        self,
        project: Project,
        voice_mapping: VoiceMapping | None,
        bgm_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.mapping = voice_mapping
        self.bgm_dir = bgm_dir
        self._partial_paths: list[Path] = []

    def request_stop(self) -> None:
        super().request_stop()
        self.emit_log("Render stop requested; cleanup will run after current ffmpeg step")

    def _stop_requested(self) -> bool:
        try:
            return self.stop_event.is_set()
        except RuntimeError:
            return False

    def _cleanup_partial_outputs(self) -> None:
        for path in self._partial_paths:
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink()
            except OSError:
                pass

    def _cancel_if_stopped(self, stage: str) -> bool:
        if not self._stop_requested():
            return False
        self._cleanup_partial_outputs()
        self.finished_fail.emit(f"Đã dừng render tại {stage}; đã xóa output tạm")
        return True

    async def _async_run(self) -> None:
        timeline_path = self.project.paths.voice_matching_timeline_json
        master_audio = self.project.paths.master_voice_wav
        if not timeline_path.exists():
            self.finished_fail.emit("Thiếu voice_matching_timeline.json — chạy Process Voice trước")
            return
        if not master_audio.exists():
            self.finished_fail.emit("Thiếu voice/master_voice.wav — chạy Process Voice trước")
            return

        aspect = self.project.scenes_json.meta.aspect_ratio
        canvas_w, canvas_h = (1080, 1920) if aspect == "9:16" else (1920, 1080)

        temp_dir = self.project.paths.temp_dir
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        except Exception as e:
            self.finished_fail.emit(f"Không đọc được voice_matching_timeline.json: {e}")
            return

        scenes_by_id = {scene.id: scene.model_dump() for scene in self.project.scenes}
        visual_paths: dict[str, Path] = {}
        for scene in self.project.scenes:
            asset_key = _visual_state_key(scene.visual_type)
            visual_state = self.project.get_scene_state(scene.id).get(asset_key, {})
            visual_path = _resolve_path(self.project, visual_state.get("path"))
            if visual_path is None:
                reason = f"visual ({asset_key}) chưa ready"
                self.scene_failed.emit(scene.id, reason)
                self.emit_log(f"❌ {scene.id}: {reason}")
                return
            visual_paths[scene.id] = visual_path

        self.emit_log("Render visual timeline (voice stays continuous)...")
        final_video_only = temp_dir / "final_video_only.mp4"
        timeline_work_dir = temp_dir / "timeline_segments"
        self._partial_paths = [
            final_video_only,
            timeline_work_dir,
            self.project.paths.root / "final.ass",
        ]
        try:
            await asyncio.to_thread(
                render_timeline_visuals,
                timeline,
                scenes_by_id,
                visual_paths,
                final_video_only,
                timeline_work_dir,
                canvas_w,
                canvas_h,
            )
        except Exception as e:
            self.finished_fail.emit(f"render_timeline_visuals: {e}")
            return
        if self._cancel_if_stopped("visual timeline"):
            return

        ass_path: Path | None = self.project.paths.root / "final.ass"
        if self.mapping is not None:
            mapping_dict = self.mapping.model_dump(mode="json")
            self.emit_log("Generate final.ass (karaoke)...")
            try:
                await asyncio.to_thread(
                    generate_final_ass,
                    voice_mapping=mapping_dict,
                    output_path=ass_path,
                    video_width=canvas_w,
                    video_height=canvas_h,
                )
            except Exception as e:
                self.finished_fail.emit(f"generate_final_ass: {e}")
                return
            if self._cancel_if_stopped("subtitle"):
                return
        else:
            ass_path = None
            self.emit_log("No voice_mapping subtitle phrases; render without ASS events")

        final_path = self.project.paths.final_mp4
        if final_path not in self._partial_paths:
            self._partial_paths.append(final_path)
        try:
            bgm_files = pick_bgm_files(self.bgm_dir)
            if bgm_files:
                self.emit_log(
                    f"Burn ASS + loudnorm voice + mix BGM ({len(bgm_files)} files, -17dB)..."
                )
            else:
                self.emit_log("Burn ASS + loudnorm master voice (no BGM)...")
            await asyncio.to_thread(
                burn_subtitle_mix_master_audio_bgm,
                final_video_only,
                master_audio,
                ass_path,
                final_path,
                self.bgm_dir,
            )
        except Exception as e:
            self.finished_fail.emit(f"final audio/subtitle pass: {e}")
            return
        if self._cancel_if_stopped("final mux"):
            return

        try:
            final_video_only.unlink()
        except OSError:
            pass

        self.emit_log(f"✓ final.mp4: {final_path}")
        self.finished_ok.emit(str(final_path))
