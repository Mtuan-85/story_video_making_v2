"""Path resolution utilities for project layout.

A project lives at projects/{project_name}/ and contains:
  scenes.json, state.json, sources/, voice/, bgm/, temp/, final.mp4
"""

from __future__ import annotations

from pathlib import Path


class ProjectPaths:
    """Resolve all standard paths for a single project directory."""

    def __init__(self, project_dir: Path):
        self.root = Path(project_dir).resolve()

    @property
    def scenes_json(self) -> Path:
        return self.root / "scenes.json"

    @property
    def state_json(self) -> Path:
        return self.root / "state.json"

    @property
    def sources_dir(self) -> Path:
        return self.root / "sources"

    @property
    def voice_dir(self) -> Path:
        return self.root / "voice"

    @property
    def bgm_dir(self) -> Path:
        return self.root / "bgm"

    @property
    def temp_dir(self) -> Path:
        return self.root / "temp"

    @property
    def final_mp4(self) -> Path:
        return self.root / "final.mp4"

    def image_path(self, scene_index: int) -> Path:
        """sources/pic{N}.jpg — N is 1-based."""
        return self.sources_dir / f"pic{scene_index}.jpg"

    def video_path(self, scene_index: int) -> Path:
        """sources/vid{N}.mp4 — N is 1-based."""
        return self.sources_dir / f"vid{scene_index}.mp4"

    def voice_batch_path(self, batch_id: int) -> Path:
        return self.voice_dir / f"batch_{batch_id}.mp3"

    def voice_scene_path(self, scene_id: str) -> Path:
        return self.voice_dir / f"scene_{scene_id}.mp3"

    def voice_manifest(self) -> Path:
        return self.voice_dir / "manifest.json"

    @property
    def voice_mapping_json(self) -> Path:
        return self.root / "voice_mapping.json"

    @property
    def renders_dir(self) -> Path:
        return self.root / "renders"

    def subtitle_dir(self, scene_id: str) -> Path:
        return self.temp_dir / f"subtitle_{scene_id}"

    def composite_scene(self, scene_id: str) -> Path:
        return self.temp_dir / f"scene_{scene_id}.mp4"

    def ensure_dirs(self) -> None:
        """Create standard subdirectories if they don't exist."""
        for d in (self.sources_dir, self.voice_dir, self.bgm_dir, self.temp_dir):
            d.mkdir(parents=True, exist_ok=True)
