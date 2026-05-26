"""Native timeline render pipeline: visual timeline → master voice final mux."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from core.voice_mapping import SubtitlePhrase, VoiceMapping, WordTimestamp
from render.bgm_mixer import (
    burn_subtitle_mix_master_audio_bgm,
    pick_bgm_files,
)
from render.timeline_visual import FPS, render_timeline_visuals
from voice.ass_generator import generate_final_ass
from workers._async_thread import AsyncTaskWorker
from workers.process_registry import terminate_registered_processes


def count_subtitle_phrases(mapping: VoiceMapping | None) -> int:
    """Count karaoke phrase events available to ASS generation."""
    if mapping is None:
        return 0
    return sum(len(scene.subtitle_phrases) for scene in mapping.scenes)


def _chunk_subtitle_words(words: list[WordTimestamp], max_chars: int = 50) -> list[list[WordTimestamp]]:
    chunks: list[list[WordTimestamp]] = []
    current: list[WordTimestamp] = []
    current_chars = 0
    for word in words:
        word_len = len(word.word)
        next_chars = current_chars + word_len + (1 if current else 0)
        if current and next_chars > max_chars:
            chunks.append(current)
            current = [word]
            current_chars = word_len
        else:
            current.append(word)
            current_chars = next_chars
    if current:
        chunks.append(current)
    return chunks


def synthesize_missing_subtitle_phrases(
    mapping: VoiceMapping,
    scenes_by_id: dict[str, dict],
) -> int:
    """Backfill karaoke from scene script when old mapping lacks Whisper phrases.

    This keeps old projects renderable. Process Voice output with real Whisper
    word timings remains preferred and is never overwritten.
    """
    filled = 0
    for assignment in mapping.scenes:
        if assignment.subtitle_phrases or assignment.is_silent:
            continue
        if assignment.voice_in is None or assignment.voice_out is None:
            continue
        voice_in = float(assignment.voice_in)
        voice_out = float(assignment.voice_out)
        if voice_out <= voice_in:
            continue
        script = str((scenes_by_id.get(assignment.id) or {}).get("script") or "").strip()
        tokens = [token.strip() for token in script.split() if token.strip()]
        if not tokens:
            continue

        word_duration = (voice_out - voice_in) / len(tokens)
        timed_words: list[WordTimestamp] = []
        for idx, token in enumerate(tokens):
            start = voice_in + idx * word_duration
            end = voice_out if idx == len(tokens) - 1 else voice_in + (idx + 1) * word_duration
            timed_words.append(
                WordTimestamp(
                    word=token,
                    start=round(start, 3),
                    end=round(end, 3),
                )
            )

        assignment.subtitle_phrases = [
            SubtitlePhrase(
                text=" ".join(word.word for word in chunk),
                start=chunk[0].start,
                end=chunk[-1].end,
                words=chunk,
            )
            for chunk in _chunk_subtitle_words(timed_words)
        ]
        filled += len(assignment.subtitle_phrases)
    return filled


def sync_mapping_pauses_from_timeline(mapping: VoiceMapping, timeline: dict) -> None:
    """Update freeze_pause_after so ASS cursor matches native visual timeline."""
    scene_items = [
        item for item in (timeline.get("timeline") or [])
        if item.get("type") == "scene"
        and item.get("scene_id")
        and item.get("render_in") is not None
        and item.get("render_out") is not None
    ]
    pause_by_scene: dict[str, float] = {}
    for idx, item in enumerate(scene_items):
        scene_id = str(item["scene_id"])
        render_out = float(item["render_out"])
        pause = 0.0
        if idx + 1 < len(scene_items):
            next_in = float(scene_items[idx + 1]["render_in"])
            pause = max(0.0, next_in - render_out)
        pause_by_scene[scene_id] = round(pause, 3)

    for assignment in mapping.scenes:
        if assignment.id in pause_by_scene:
            assignment.freeze_pause_after = pause_by_scene[assignment.id]


def load_latest_voice_mapping(project: Project, fallback: VoiceMapping | None) -> VoiceMapping | None:
    """Prefer the on-disk voice_mapping.json so render cannot use stale UI state."""
    mapping_path = project.paths.voice_mapping_json
    if mapping_path.exists():
        data = json.loads(mapping_path.read_text(encoding="utf-8"))
        mapping = VoiceMapping.model_validate(data)
        project.voice_mapping = mapping
        return mapping
    return fallback


def resolve_render_master_audio(project: Project) -> Path:
    """Return the active master voice selected by the latest successful Whisper."""
    active_path = getattr(project, "active_master_voice_path", None)
    if active_path is not None:
        return Path(active_path)
    return project.paths.master_voice_wav


def visual_cache_is_reusable(
    cache_path: Path,
    timeline_path: Path,
    scenes_json_path: Path | None,
    visual_paths: dict[str, Path],
    scenes_by_id: dict[str, dict] | None = None,
) -> bool:
    """Return True when final_video_only.mp4 is newer than visual inputs."""
    cache_path = Path(cache_path)
    if not cache_path.exists() or cache_path.stat().st_size <= 0:
        return False

    if scenes_by_id is not None:
        meta_path = cache_path.with_suffix(".json")
        if not meta_path.exists():
            return False
        try:
            saved = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        current = build_visual_cache_signature(timeline_path, scenes_by_id, visual_paths)
        return saved.get("signature") == current

    cache_mtime = cache_path.stat().st_mtime
    dependency_paths = [Path(timeline_path)]
    if scenes_json_path is not None:
        dependency_paths.append(Path(scenes_json_path))
    dependency_paths.extend(Path(p) for p in visual_paths.values())

    for path in dependency_paths:
        if path.exists() and path.stat().st_mtime > cache_mtime:
            return False
    return True


def _file_signature(path: Path) -> dict:
    path = Path(path)
    stat = path.stat()
    return {
        "path": str(path.resolve()).replace("\\", "/"),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def build_visual_cache_signature(
    timeline_path: Path,
    scenes_by_id: dict[str, dict],
    visual_paths: dict[str, Path],
) -> dict:
    """Build a stable signature for inputs that affect visual-only rendering."""
    scene_signatures = []
    for scene_id in sorted(visual_paths):
        scene = scenes_by_id.get(scene_id) or {}
        visual_path = Path(visual_paths[scene_id])
        scene_signatures.append(
            {
                "scene_id": scene_id,
                "visual_type": scene.get("visual_type"),
                "effect": scene.get("effect"),
                "visual": _file_signature(visual_path),
            }
        )
    return {
        "version": 1,
        "timeline": _file_signature(Path(timeline_path)),
        "scenes": scene_signatures,
    }


def save_visual_cache_metadata(meta_path: Path, signature: dict) -> None:
    meta_path = Path(meta_path)
    meta_path.write_text(
        json.dumps({"signature": signature}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
        stopped = terminate_registered_processes(force=True)
        self.emit_log("Render stop requested; cleanup will run after current ffmpeg step")
        if stopped:
            self.emit_log(f"Stopped {stopped} running ffmpeg subprocess(es)")

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
        master_audio = resolve_render_master_audio(self.project)
        if not timeline_path.exists():
            self.finished_fail.emit("Thiếu voice_matching_timeline.json — chạy Process Voice trước")
            return
        if not master_audio.exists():
            self.finished_fail.emit(
                f"Thiếu master audio active: {master_audio} — chạy Process Voice/Whisper trước"
            )
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

        try:
            self.mapping = load_latest_voice_mapping(self.project, self.mapping)
        except Exception as e:
            self.finished_fail.emit(f"Không đọc được voice_mapping.json: {e}")
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

        final_video_only = temp_dir / "final_video_only.mp4"
        timeline_work_dir = temp_dir / "timeline_segments"
        self._partial_paths = [
            timeline_work_dir,
            self.project.paths.root / "final.ass",
        ]
        visual_cache_ok = visual_cache_is_reusable(
            final_video_only,
            timeline_path,
            self.project.paths.scenes_edited,
            visual_paths,
            scenes_by_id,
        )
        def _visual_progress(done: int, total: int, segment) -> None:
            pct = int(round(done * 100 / max(1, total)))
            self.progress.emit(done, total)
            self.emit_log(
                f"Visual timeline: {done}/{total} ({pct}%) "
                f"{segment.kind} {segment.scene_id}"
            )

        if visual_cache_ok:
            self.emit_log(f"Reuse visual cache: {final_video_only.name}")
        else:
            self.emit_log("Render visual timeline (voice stays continuous)...")
            self._partial_paths.append(final_video_only)
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
                    FPS,
                    _visual_progress,
                )
            except Exception as e:
                self.finished_fail.emit(f"render_timeline_visuals: {e}")
                return
            try:
                save_visual_cache_metadata(
                    final_video_only.with_suffix(".json"),
                    build_visual_cache_signature(timeline_path, scenes_by_id, visual_paths),
                )
            except Exception as e:
                self.emit_log(f"⚠ Cannot save visual cache metadata: {e}")
            if self._cancel_if_stopped("visual timeline"):
                return

        ass_path: Path | None = self.project.paths.root / "final.ass"
        if self.mapping is not None:
            sync_mapping_pauses_from_timeline(self.mapping, timeline)
            fallback_count = synthesize_missing_subtitle_phrases(self.mapping, scenes_by_id)
            if fallback_count:
                self.emit_log(
                    f"⚠ Synthesized {fallback_count} karaoke phrase events from scene scripts "
                    "because voice_mapping had no Whisper subtitle phrases. "
                    "Run Process Voice again for exact word timing."
                )
            mapping_dict = self.mapping.model_dump(mode="json")
            phrase_count = count_subtitle_phrases(self.mapping)
            self.emit_log(f"Generate final.ass (karaoke, {phrase_count} phrase events)...")
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
            if phrase_count <= 0:
                self.emit_log(
                    "⚠ voice_mapping has 0 subtitle phrases; final.ass will have no karaoke. "
                    "Run Process Voice again to rebuild mapping from Whisper words."
                )
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
                -17.0,
                2.0,
                self.emit_log,
            )
        except Exception as e:
            self.finished_fail.emit(f"final audio/subtitle pass: {e}")
            return
        if self._cancel_if_stopped("final mux"):
            return

        self.emit_log(f"✓ final.mp4: {final_path}")
        self.finished_ok.emit(str(final_path))
