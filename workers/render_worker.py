"""Async render pipeline: composite each scene → concat → optional BGM."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from core.schema import Scene
from core.voice_mapping import VoiceMapping
from render.assemble import assemble_final
from render.composite import composite_scene
from workers._async_thread import AsyncTaskWorker


def _visual_state_key(visual_type: str) -> str:
    """Map Scene.visual_type → key in state.scenes[id] dict.

    image_grok → "image"; everything else (video_grok, slideshow,
    ken_burns_*) lands under "video".
    """
    return "image" if visual_type == "image_grok" else "video"


def _resolve_path(project: Project, rel_or_abs: str | None) -> Path | None:
    if not rel_or_abs:
        return None
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = project.paths.root / p
    return p if p.exists() else None


class RenderWorker(AsyncTaskWorker):
    """Compose every scene then assemble into final.mp4.

    Signals:
        scene_started(scene_id)
        scene_done(scene_id)
        scene_failed(scene_id, reason)
        progress(current, total)
        finished_ok(output_path: str)
        finished_fail(reason)
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
        voice_mapping: VoiceMapping,
        bgm_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.mapping = voice_mapping
        self.bgm_dir = bgm_dir

    async def _async_run(self) -> None:
        scenes: list[Scene] = list(self.project.scenes)
        total = len(scenes)
        scene_outputs: list[Path] = []
        aspect = self.project.scenes_json.meta.aspect_ratio
        canvas_w, canvas_h = (1080, 1920) if aspect == "9:16" else (1920, 1080)
        renders_dir = self.project.paths.renders_dir
        renders_dir.mkdir(parents=True, exist_ok=True)

        for i, scene in enumerate(scenes, start=1):
            if self.stop_event.is_set():
                self.emit_log("Đã hủy render")
                self.finished_fail.emit("stopped")
                return

            self.scene_started.emit(scene.id)
            self.progress.emit(i, total)

            voice_file_path: Path | None = None
            voice_assignment = None
            phrases = []
            if not self.mapping.is_silent(scene.id):
                found = self.mapping.get_assignment_for_scene(scene.id)
                if found is not None:
                    vf, assignment = found
                    voice_file_path = _resolve_path(self.project, vf.file)
                    if voice_file_path is None:
                        self.emit_log(f"⚠ {scene.id}: voice file '{vf.file}' không thấy trên disk → silent")
                    else:
                        voice_assignment = assignment
                        phrases = assignment.subtitle_phrases

            asset_key = _visual_state_key(scene.visual_type)
            visual_state = self.project.get_scene_state(scene.id).get(asset_key, {})
            visual_path = _resolve_path(self.project, visual_state.get("path"))
            if visual_path is None:
                reason = f"visual ({asset_key}) chưa ready"
                self.scene_failed.emit(scene.id, reason)
                self.emit_log(f"❌ {scene.id}: {reason}")
                continue

            output = renders_dir / f"{scene.id}.mp4"
            self.emit_log(
                f"[{i}/{total}] composite {scene.id} ({scene.visual_type}, "
                f"{'voice' if voice_assignment else 'silent'})..."
            )
            try:
                result = await composite_scene(
                    scene_id=scene.id,
                    voice_file_path=voice_file_path,
                    voice_assignment=voice_assignment,
                    visual_path=visual_path,
                    visual_type=scene.visual_type,
                    declared_duration=float(scene.duration),
                    subtitle_phrases=list(phrases),
                    output_path=output,
                    aspect_ratio=aspect,
                    is_first=(i == 1),
                    is_last=(i == total),
                )
            except Exception as e:
                self.scene_failed.emit(scene.id, str(e))
                self.emit_log(f"❌ {scene.id}: {e}")
                continue

            if not result.get("ok"):
                self.scene_failed.emit(scene.id, result.get("error", "unknown")[:300])
                self.emit_log(f"❌ {scene.id}: {result.get('error', '')[:200]}")
                continue

            scene_outputs.append(output)
            self.scene_done.emit(scene.id)
            self.emit_log(
                f"✓ {scene.id} composed ({result.get('duration', 0):.2f}s)"
            )

        if not scene_outputs:
            self.finished_fail.emit("Không có scene nào composite OK")
            return

        if self.stop_event.is_set():
            self.finished_fail.emit("stopped")
            return

        self.emit_log(f"Assemble {len(scene_outputs)} scenes → final.mp4...")
        final_path = self.project.paths.final_mp4
        try:
            ar = await assemble_final(
                scene_videos=scene_outputs,
                output_path=final_path,
                bgm_dir=self.bgm_dir,
                canvas_w=canvas_w,
                canvas_h=canvas_h,
            )
        except Exception as e:
            self.finished_fail.emit(f"assemble exception: {e}")
            return

        if not ar.get("ok"):
            self.finished_fail.emit(ar.get("error", "assemble_failed")[:300])
            return

        self.emit_log(
            f"✓ final.mp4 ({'with BGM' if ar.get('has_bgm') else 'no BGM'}): {final_path}"
        )
        self.finished_ok.emit(str(final_path))
