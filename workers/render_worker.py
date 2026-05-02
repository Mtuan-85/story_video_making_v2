"""Async render pipeline (Plan D): composite each scene → concat → ASS burn."""

from __future__ import annotations

import asyncio
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from core.schema import Scene
from core.voice_mapping import VoiceMapping
from render.assemble import apply_ass_subtitle, assemble_concat
from render.composite import composite_scene
from voice.ass_generator import generate_final_ass
from workers._async_thread import AsyncTaskWorker


def _visual_state_key(visual_type: str) -> str:
    """Map Scene.visual_type → key in state.scenes[id] dict."""
    return "image" if visual_type == "image_grok" else "video"


def _resolve_path(project: Project, rel_or_abs: str | None) -> Path | None:
    if not rel_or_abs:
        return None
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = project.paths.root / p
    return p if p.exists() else None


class RenderWorker(AsyncTaskWorker):
    """Plan D render pipeline.

    Pass 1: composite per scene (visual + voice slice, NO subtitle).
    Pass 2: assemble_concat → final_raw.mp4.
    Pass 3: generate_final_ass from voice_mapping → final.ass.
    Pass 4: apply_ass_subtitle (libass burn) → final.mp4.
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
        self.bgm_dir = bgm_dir  # BGM mixing not wired in Plan D pipeline yet

    async def _async_run(self) -> None:
        scenes: list[Scene] = list(self.project.scenes)
        total = len(scenes)
        if total == 0:
            self.finished_fail.emit("Không có scene nào để render")
            return

        aspect = self.project.scenes_json.meta.aspect_ratio
        canvas_w, canvas_h = (1080, 1920) if aspect == "9:16" else (1920, 1080)

        renders_dir = self.project.paths.renders_dir
        renders_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = self.project.paths.temp_dir
        temp_dir.mkdir(parents=True, exist_ok=True)

        mapping_dict = self.mapping.model_dump(mode="json")
        voice_files_meta = mapping_dict.get("voice_files", [])
        voice_scenes = {vs["id"]: vs for vs in mapping_dict.get("scenes", [])}

        scene_outputs: list[Path] = []

        # === Pass 1: composite each scene (no subtitle) ===
        for i, scene in enumerate(scenes, start=1):
            if self.stop_event.is_set():
                self.emit_log("Đã hủy render")
                self.finished_fail.emit("stopped")
                return

            self.scene_started.emit(scene.id)
            self.progress.emit(i, total)

            voice_scene = voice_scenes.get(scene.id)
            if voice_scene is None:
                reason = f"{scene.id}: không có entry trong voice_mapping"
                self.scene_failed.emit(scene.id, reason)
                self.emit_log(f"❌ {reason}")
                continue

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
                f"[{i}/{total}] composite {scene.id} "
                f"({scene.visual_type}, "
                f"{'silent' if voice_scene.get('is_silent') else 'voice'})..."
            )
            try:
                await asyncio.to_thread(
                    composite_scene,
                    scene=scene.model_dump(),
                    voice_scene=voice_scene,
                    visual_path=visual_path,
                    voice_files=voice_files_meta,
                    project_root=self.project.paths.root,
                    output_path=output,
                    width=canvas_w,
                    height=canvas_h,
                )
            except Exception as e:
                self.scene_failed.emit(scene.id, str(e))
                self.emit_log(f"❌ {scene.id}: {e}")
                continue

            scene_outputs.append(output)
            self.scene_done.emit(scene.id)
            self.emit_log(f"✓ {scene.id} composed → {output.name}")

        if not scene_outputs:
            self.finished_fail.emit("Không có scene nào composite OK")
            return
        if self.stop_event.is_set():
            self.finished_fail.emit("stopped")
            return

        # === Pass 2: concat ===
        self.emit_log(f"Concat {len(scene_outputs)} scenes...")
        final_raw = temp_dir / "final_raw.mp4"
        try:
            await asyncio.to_thread(assemble_concat, scene_outputs, final_raw)
        except Exception as e:
            self.finished_fail.emit(f"assemble_concat: {e}")
            return

        # === Pass 3: gen ASS ===
        ass_path = self.project.paths.root / "final.ass"
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

        # === Pass 4: burn ASS ===
        final_path = self.project.paths.final_mp4
        self.emit_log("Burn ASS (libass)...")
        try:
            await asyncio.to_thread(apply_ass_subtitle, final_raw, ass_path, final_path)
        except Exception as e:
            self.finished_fail.emit(f"apply_ass_subtitle: {e}")
            return

        try:
            final_raw.unlink()
        except OSError:
            pass

        self.emit_log(f"✓ final.mp4: {final_path}")
        self.finished_ok.emit(str(final_path))
