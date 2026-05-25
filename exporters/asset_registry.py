"""Resolve and register every asset needed by the Kdenlive export.

Per Sprint 2 §10: every visual_source, freeze frame, placeholder, and
the master audio must be registered with a stable producer_id BEFORE
XML write. This module:

  1. Walks the timeline + master audio path.
  2. Resolves each asset relative to project_root.
  3. Generates freeze frames for video pauses.
  4. Generates placeholders for missing assets (if policy=placeholder).
  5. Returns a dict[clip_key → AssetEntry] keyed by clip identity so the
     MLT builder can look up producer paths deterministically.

Clip key convention:
    scene:{scene_id}         → primary scene visual
    pause:{beat_id}          → beat_pause visual (freeze or reused image)
    audio:master             → master_voice.wav
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger as log

from exporters.freeze_frame import extract_last_frame
from exporters.placeholder import generate_placeholder


# Policy values for missing_asset_policy
POLICY_STRICT = "strict"
POLICY_PLACEHOLDER = "placeholder"


@dataclass
class AssetEntry:
    """One asset registered for the export."""
    clip_key: str               # e.g. "scene:SCENE-01", "pause:beat-01"
    producer_id: str            # MLT producer id (stable: prod_v_0, prod_a_0)
    path: Path                  # absolute path on disk
    asset_type: str             # "image" | "video" | "audio"
    display_name: str           # human-readable clip name (e.g. "SCENE-01")
    is_generated: bool = False  # True for freeze_frames / placeholders
    is_placeholder: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class AssetRegistry:
    """All assets needed for one Kdenlive export."""
    project_root: Path
    output_dir: Path
    fps: int
    width: int
    height: int
    entries: dict[str, AssetEntry] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_freeze_frames: list[str] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)

    def get(self, clip_key: str) -> Optional[AssetEntry]:
        return self.entries.get(clip_key)

    def all_entries(self) -> list[AssetEntry]:
        return list(self.entries.values())

    @property
    def generated_dir(self) -> Path:
        return self.output_dir / "generated"


def _resolve_source(project_root: Path, rel_or_abs: str) -> Path:
    """Convert visual_source to absolute path under project_root if relative."""
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = project_root / p
    return p


def _detect_asset_type(path: Path) -> str:
    """Image vs video by extension."""
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        return "image"
    if ext in (".mp4", ".mov", ".webm", ".mkv", ".avi"):
        return "video"
    return "unknown"


def build_registry(
    timeline_items: list[dict],
    master_audio_path: Path,
    project_root: Path,
    output_dir: Path,
    fps: int = 30,
    width: int = 1920,
    height: int = 1080,
    missing_asset_policy: str = POLICY_PLACEHOLDER,
) -> AssetRegistry:
    """Walk timeline, resolve every asset, generate missing where allowed.

    Args:
        timeline_items: from voice_matching_timeline.json["timeline"]
        master_audio_path: master_voice.wav (must exist)
        project_root: root for relative path resolution
        output_dir: where to write .kdenlive (used to anchor generated/)
        missing_asset_policy: "strict" or "placeholder"

    Returns:
        AssetRegistry. Check `registry.errors` before XML write.
    """
    project_root = Path(project_root).resolve()
    output_dir = Path(output_dir).resolve()
    master_audio_path = Path(master_audio_path).resolve()

    registry = AssetRegistry(
        project_root=project_root,
        output_dir=output_dir,
        fps=fps,
        width=width,
        height=height,
    )

    # ---- Master audio ----
    if not master_audio_path.exists():
        registry.errors.append(f"Master audio not found: {master_audio_path}")
    else:
        registry.entries["audio:master"] = AssetEntry(
            clip_key="audio:master",
            producer_id="prod_audio_master",
            path=master_audio_path,
            asset_type="audio",
            display_name="master_voice",
        )

    # ---- Build a quick lookup: scene_id → its scene item (for pause freeze) ----
    scene_item_by_id: dict[str, dict] = {}
    for it in timeline_items:
        if it.get("type") == "scene" and it.get("scene_id"):
            scene_item_by_id[it["scene_id"]] = it

    # ---- Walk timeline ----
    scene_visual_counter = 0
    pause_counter = 0

    for it in timeline_items:
        itype = it.get("type")

        if itype == "scene":
            scene_id = it.get("scene_id") or f"SCENE_{scene_visual_counter}"
            clip_key = f"scene:{scene_id}"
            if clip_key in registry.entries:
                continue  # already registered (shouldn't repeat normally)

            visual_source = it.get("visual_source") or ""
            if not visual_source:
                registry.errors.append(f"{scene_id}: missing visual_source")
                continue

            abs_path = _resolve_source(project_root, visual_source)
            asset_type = _detect_asset_type(abs_path)

            entry = _register_or_placeholder(
                registry, scene_id, clip_key, abs_path, asset_type,
                missing_asset_policy=missing_asset_policy,
            )
            if entry:
                entry.producer_id = f"prod_v_{scene_visual_counter}"
                entry.display_name = scene_id
                scene_visual_counter += 1

        elif itype == "beat_pause":
            beat_id = it.get("beat_id") or f"beat_pause_{pause_counter}"
            clip_key = f"pause:{beat_id}"
            if clip_key in registry.entries:
                continue

            after_scene_id = it.get("after_scene_id")
            entry = _register_pause(
                registry,
                beat_id=beat_id,
                clip_key=clip_key,
                after_scene_id=after_scene_id,
                scene_item_by_id=scene_item_by_id,
                missing_asset_policy=missing_asset_policy,
            )
            if entry:
                entry.producer_id = f"prod_v_pause_{pause_counter}"
                entry.display_name = f"{beat_id}_pause"
                pause_counter += 1

    log.info(
        f"AssetRegistry: {len(registry.entries)} assets "
        f"({scene_visual_counter} scenes, {pause_counter} pauses, "
        f"{len(registry.generated_freeze_frames)} freezes, "
        f"{len(registry.placeholders)} placeholders)"
    )
    if registry.errors:
        log.error(f"AssetRegistry errors: {len(registry.errors)}")
    return registry


def _register_or_placeholder(
    registry: AssetRegistry,
    scene_id: str,
    clip_key: str,
    abs_path: Path,
    asset_type: str,
    missing_asset_policy: str,
) -> Optional[AssetEntry]:
    """Register a scene visual, falling back to placeholder if missing."""
    if abs_path.exists():
        entry = AssetEntry(
            clip_key=clip_key,
            producer_id="",        # caller assigns
            path=abs_path,
            asset_type=asset_type,
            display_name=scene_id,
        )
        registry.entries[clip_key] = entry
        return entry

    # Missing source
    if missing_asset_policy == POLICY_STRICT:
        registry.errors.append(f"{scene_id}: missing visual source {abs_path}")
        return None

    # Placeholder policy
    placeholder_path = registry.generated_dir / "placeholders" / f"{scene_id}_placeholder.jpg"
    if generate_placeholder(
        scene_id=scene_id,
        expected_path=str(abs_path).replace("\\", "/"),
        output_jpg=placeholder_path,
        width=registry.width,
        height=registry.height,
    ):
        registry.placeholders.append(str(placeholder_path))
        registry.warnings.append(f"{scene_id}: placeholder generated (missing {abs_path.name})")
        entry = AssetEntry(
            clip_key=clip_key,
            producer_id="",
            path=placeholder_path,
            asset_type="image",
            display_name=f"{scene_id}_placeholder",
            is_generated=True,
            is_placeholder=True,
        )
        registry.entries[clip_key] = entry
        return entry

    registry.errors.append(f"{scene_id}: placeholder generation failed")
    return None


def _register_pause(
    registry: AssetRegistry,
    beat_id: str,
    clip_key: str,
    after_scene_id: Optional[str],
    scene_item_by_id: dict,
    missing_asset_policy: str,
) -> Optional[AssetEntry]:
    """Register beat-pause visual. Reuse image source OR generate freeze."""
    if after_scene_id is None or after_scene_id not in scene_item_by_id:
        # Fall back to placeholder so timeline doesn't break
        return _make_pause_placeholder(
            registry, beat_id, clip_key,
            reason="no preceding scene_id"
        )

    prev_scene = scene_item_by_id[after_scene_id]
    prev_visual_type = (prev_scene.get("visual_type") or "").lower()
    prev_source = _resolve_source(
        registry.project_root, prev_scene.get("visual_source") or "",
    )

    if not prev_source.exists():
        return _make_pause_placeholder(
            registry, beat_id, clip_key,
            reason=f"previous scene {after_scene_id} visual missing",
        )

    # Image scene: reuse the SAME image file as the pause clip.
    # (No file copy needed — MLT can reference one producer multiple times
    # via separate playlist entries.)
    if prev_visual_type == "image":
        entry = AssetEntry(
            clip_key=clip_key,
            producer_id="",
            path=prev_source,
            asset_type="image",
            display_name=f"{beat_id}_pause",
        )
        registry.entries[clip_key] = entry
        return entry

    # Video / slideshow: extract last frame
    freeze_path = registry.generated_dir / "freeze_frames" / f"{after_scene_id}_freeze.jpg"
    if extract_last_frame(prev_source, freeze_path):
        registry.generated_freeze_frames.append(str(freeze_path))
        entry = AssetEntry(
            clip_key=clip_key,
            producer_id="",
            path=freeze_path,
            asset_type="image",
            display_name=f"{beat_id}_pause",
            is_generated=True,
        )
        registry.entries[clip_key] = entry
        return entry

    # Freeze failed → placeholder fallback per §9.3
    return _make_pause_placeholder(
        registry, beat_id, clip_key,
        reason=f"freeze-frame extraction failed for {after_scene_id}",
    )


def _make_pause_placeholder(
    registry: AssetRegistry,
    beat_id: str,
    clip_key: str,
    reason: str,
) -> Optional[AssetEntry]:
    placeholder_path = (
        registry.generated_dir / "placeholders" / f"{beat_id}_pause_missing_freeze.jpg"
    )
    if generate_placeholder(
        scene_id=f"{beat_id}_pause",
        expected_path=f"(no source — {reason})",
        output_jpg=placeholder_path,
        width=registry.width,
        height=registry.height,
    ):
        registry.placeholders.append(str(placeholder_path))
        registry.warnings.append(f"{beat_id}_pause: placeholder ({reason})")
        entry = AssetEntry(
            clip_key=clip_key,
            producer_id="",
            path=placeholder_path,
            asset_type="image",
            display_name=f"{beat_id}_pause",
            is_generated=True,
            is_placeholder=True,
        )
        registry.entries[clip_key] = entry
        return entry

    registry.errors.append(f"{beat_id}_pause: placeholder generation failed ({reason})")
    return None
