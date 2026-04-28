"""
Worker v3 - bỏ max_objects, Claude tự group.
"""

from pathlib import Path
import json

from PyQt6.QtCore import QThread, pyqtSignal

from preprocess import preprocess_scene, find_scene_image
from claude_runner import run_claude_analyze, validate_plan
from renderer import render_video, PRESETS


class GenerationWorker(QThread):
    status = pyqtSignal(str)
    finished_ok = pyqtSignal(Path)
    failed = pyqtSignal(str)

    def __init__(self, folder: Path, duration: int, preset: str,
                 hint: str = "", use_cache: bool = True,
                 bg_method: str = "auto"):
        super().__init__()
        self.folder = Path(folder)
        self.duration = duration
        self.preset = preset
        self.hint = hint
        self.use_cache = use_cache
        self.bg_method = bg_method

    def run(self):
        try:
            self._run_pipeline()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.failed.emit(f"{e}\n\n--- Traceback ---\n{tb}")

    def _run_pipeline(self):
        self.status.emit("🔍 Kiểm tra folder...")

        if not self.folder.exists() or not self.folder.is_dir():
            raise ValueError(f"Folder không tồn tại: {self.folder}")

        scene_path = find_scene_image(self.folder)
        self.status.emit(f"   → Scene: {scene_path.name}")

        if self.preset not in PRESETS:
            raise ValueError(f"Preset không hợp lệ: {self.preset}")
        preset = PRESETS[self.preset]

        cache_dir = self.folder / ".cache"
        processed_dir = cache_dir / "processed"
        metadata_file = processed_dir / "metadata.json"

        # Cache invalidation: scene mới hơn metadata
        need_preprocess = True
        if self.use_cache and metadata_file.exists():
            try:
                scene_mtime = scene_path.stat().st_mtime
                cache_mtime = metadata_file.stat().st_mtime
                if scene_mtime < cache_mtime:
                    need_preprocess = False
            except Exception:
                need_preprocess = True

        if need_preprocess:
            self.status.emit(f"🎨 Xóa background ({self.bg_method}) & tách objects...")
            metadata = preprocess_scene(
                scene_path=scene_path,
                cache_dir=cache_dir,
                bg_method=self.bg_method,
                log_fn=lambda msg: self.status.emit(f"   {msg}"),
            )
            self.status.emit(f"   → {len(metadata['objects'])} objects tách được")
        else:
            self.status.emit("✓ Dùng cache preprocess")
            with open(metadata_file, encoding='utf-8') as f:
                metadata = json.load(f)

        # ─── Claude analyze ───
        self.status.emit("🎬 Claude design animation (group + pacing)...")
        if self.hint:
            self.status.emit(
                f"   → Hint: {self.hint[:80]}{'...' if len(self.hint) > 80 else ''}"
            )

        plan = run_claude_analyze(
            folder=self.folder,
            scene_path=scene_path,
            processed_dir=processed_dir,
            duration=self.duration,
            canvas_w=preset["width"],
            canvas_h=preset["height"],
            hint=self.hint,
        )

        available = [obj["filename"] for obj in metadata["objects"]]
        validate_plan(plan, available, self.duration, min_scenes=3)

        self.status.emit(f"   → {len(plan['scenes'])} scenes (groups):")
        for i, scene in enumerate(plan["scenes"], 1):
            objs_str = ", ".join(scene["objects"])
            rationale = scene.get("rationale", "")
            self.status.emit(
                f"      [{i}] @{scene['appear_at']:.1f}s "
                f"[{scene['animation']}] {{{objs_str}}}"
            )
            if rationale:
                self.status.emit(f"          💭 {rationale}")

        if "duration" not in plan:
            plan["duration"] = self.duration

        # ─── Render ───
        self.status.emit("🎥 Render video bằng ffmpeg...")

        movie_dir = self.folder / "movie"
        output_path = movie_dir / "final.mp4"

        render_video(
            metadata=metadata,
            plan=plan,
            processed_dir=processed_dir,
            output_path=output_path,
            preset_name=self.preset,
            progress_callback=lambda msg: self.status.emit(f"   → {msg}"),
        )

        self.status.emit("✅ Hoàn thành!")
        self.finished_ok.emit(output_path)
