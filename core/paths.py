"""Path resolution utilities for project layout.

A project lives under any directory chosen by the user. The user picks a
scenes-style JSON file (e.g. ``my_story.json``); its companions are derived
from the file stem:

    <stem>.json          — original design (selected by user)
    <stem>_edited.json   — working copy + edits (auto-cloned on first load)
    <stem>_state.json    — runtime state (per-scene asset status, warnings)

Other artefacts (sources/, voice/, bgm/, temp/, thumbnails/, renders/,
voice_mapping.json, final.mp4) are project-folder scoped and use fixed names.
Subdirectories are created lazily by writers; ``ensure_dirs()`` is kept as a
no-op for callers that prefer eager creation.
"""

from __future__ import annotations

from pathlib import Path


class ProjectPaths:
    """Resolve all standard paths for a single project, anchored at one
    scenes-style JSON file.

    Backward compat: when the file is named ``scenes.json`` (legacy
    convention) the derived stem is ``"scenes"`` so the edited file maps
    cleanly to the existing ``scenes_edited.json``. The legacy ``state.json``
    is exposed via ``legacy_state_json`` for one-shot migration on load.
    """

    # Auto-scan: stems tried (in order) when looking up scene assets in
    # sources/. First match wins. Lets users rename pic39.jpg → scene_39.jpg
    # without breaking the app.
    _IMAGE_STEMS = ("pic{n}", "pic{n:02d}", "scene_{n}", "scene_{n:02d}")
    _IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
    _VIDEO_STEMS = ("vid{n}", "vid{n:02d}", "scene_{n}", "scene_{n:02d}")
    _VIDEO_EXTS = (".mp4", ".mov", ".webm")

    def __init__(self, scenes_file: Path):
        scenes_file = Path(scenes_file).resolve()
        self.scenes_file = scenes_file
        self.root = scenes_file.parent
        self.stem = scenes_file.stem

    @property
    def scenes_json(self) -> Path:
        return self.root / f"{self.stem}.json"

    @property
    def scenes_original(self) -> Path:
        return self.scenes_json

    @property
    def scenes_edited(self) -> Path:
        return self.root / f"{self.stem}_edited.json"

    @property
    def state_json(self) -> Path:
        return self.root / f"{self.stem}_state.json"

    @property
    def ref_mapping_json(self) -> Path:
        return self.root / f"{self.stem}_ref_mapping.json"

    @property
    def s5_beats_json(self) -> Path:
        """Sprint 1 source-of-truth beat narration. e.g. Naomi2_S5.json.

        S5 = per-beat raw narration + scenes[] + pause_after_sec. S6 adds
        emotional TTS tags and must NOT be used for word matching.
        """
        return self.root / f"{self.stem}_S5.json"

    @property
    def master_voice_wav(self) -> Path:
        """Default raw master audio. Kept for existing callers."""
        return self.master_voice_raw_wav

    @property
    def legacy_master_voice_wav(self) -> Path:
        return self.voice_dir / "master_voice.wav"

    @property
    def voice_raw_dir(self) -> Path:
        return self.voice_dir / "raw"

    @property
    def voice_enhance_dir(self) -> Path:
        return self.voice_dir / "enhance"

    @property
    def voice_source_dir(self) -> Path:
        return self.voice_dir / "source"

    @property
    def voice_source_s6_dir(self) -> Path:
        return self.voice_source_dir / "s6"

    @property
    def legacy_s6_voice_dir(self) -> Path:
        return self.root / f"{self.stem}_S6_voice"

    @property
    def master_voice_raw_wav(self) -> Path:
        return self.voice_raw_dir / "master_voice.wav"

    @property
    def master_voice_enhanced_wav(self) -> Path:
        return self.voice_enhance_dir / "master_voice.wav"

    @property
    def whisper_words_raw_json(self) -> Path:
        return self.voice_raw_dir / "whisper_words.json"

    @property
    def whisper_words_enhanced_json(self) -> Path:
        return self.voice_enhance_dir / "whisper_words.json"

    @property
    def voice_pacing_operations_json(self) -> Path:
        return self.voice_enhance_dir / "voice_pacing_operations.json"

    @property
    def voice_enhance_report_json(self) -> Path:
        return self.voice_enhance_dir / "voice_enhance_report.json"

    @property
    def voice_matching_timeline_json(self) -> Path:
        """Sprint 1 output: voice_matching_timeline.json."""
        return self.voice_dir / "voice_matching_timeline.json"

    @property
    def voice_matching_diagnostics_json(self) -> Path:
        """Sprint 1 output: voice_matching_diagnostics.json."""
        return self.voice_dir / "voice_matching_diagnostics.json"

    @property
    def legacy_state_json(self) -> Path:
        """Old convention: ``state.json`` next to ``scenes.json``. Used as a
        one-shot fallback during load when no ``<stem>_state.json`` exists.
        """
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
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def kdenlive_cache_dir(self) -> Path:
        return self.cache_dir / "kdenlive"

    @property
    def final_mp4(self) -> Path:
        return self.root / "final.mp4"

    def image_path(self, scene_index: int) -> Path:
        """sources/pic{N}.jpg — N is 1-based. Default WRITE path used by
        engines/workers. Readers should use ``find_image`` instead so user
        renames (e.g. pic39.jpg → scene_39.jpg) are tolerated.
        """
        return self.sources_dir / f"pic{scene_index}.jpg"

    def video_path(self, scene_index: int) -> Path:
        """sources/vid{N}.mp4 — N is 1-based. Default WRITE path; readers
        should use ``find_video``.
        """
        return self.sources_dir / f"vid{scene_index}.mp4"

    def find_image(self, scene_index: int) -> Path | None:
        """Locate the image for ``scene_index`` under sources/ across the
        accepted stem/extension combos. Returns None when nothing matches.
        """
        return self._find_asset(scene_index, self._IMAGE_STEMS, self._IMAGE_EXTS)

    def find_video(self, scene_index: int) -> Path | None:
        """Same as ``find_image`` but for video assets."""
        return self._find_asset(scene_index, self._VIDEO_STEMS, self._VIDEO_EXTS)

    def _find_asset(
        self,
        scene_index: int,
        stems: tuple[str, ...],
        exts: tuple[str, ...],
    ) -> Path | None:
        sources = self.sources_dir
        if not sources.exists():
            return None
        for stem_tpl in stems:
            stem = stem_tpl.format(n=scene_index)
            for ext in exts:
                candidate = sources / f"{stem}{ext}"
                if candidate.exists():
                    return candidate
        return None

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

    @property
    def thumbnails_dir(self) -> Path:
        return self.root / "thumbnails"

    def thumbnail_path(self, scene_id: str) -> Path:
        return self.thumbnails_dir / f"{scene_id}.jpg"

    # ------------------------------------------------------------------
    # Edit (slideshow) artefacts — under sources/edit/
    # ------------------------------------------------------------------

    @property
    def edit_dir(self) -> Path:
        """sources/edit/ — slideshow zones + thumbs + ephemeral cache."""
        return self.sources_dir / "edit"

    def edit_zones_json(self, scene_id: str) -> Path:
        """Persistent zones state for re-edit. e.g. sources/edit/SCENE-03-zones.json"""
        return self.edit_dir / f"{scene_id}-zones.json"

    def edit_thumb(self, scene_id: str) -> Path:
        """Polygon overlay preview. e.g. sources/edit/SCENE-03-thumb.png"""
        return self.edit_dir / f"{scene_id}-thumb.png"

    def edit_cache_dir(self, scene_id: str) -> Path:
        """Ephemeral cache (Claude logs, frames). Deleted after successful render."""
        return self.edit_dir / ".cache" / scene_id

    def subtitle_dir(self, scene_id: str) -> Path:
        return self.temp_dir / f"subtitle_{scene_id}"

    def composite_scene(self, scene_id: str) -> Path:
        return self.temp_dir / f"scene_{scene_id}.mp4"

    def ensure_dirs(self) -> None:
        """No-op kept for API stability: every writer in this codebase
        already calls ``mkdir(parents=True, exist_ok=True)`` on its own
        target, so eager creation here is redundant. Callers that still
        prefer it can opt in by using the ``mkdir`` helpers directly.
        """
        return
