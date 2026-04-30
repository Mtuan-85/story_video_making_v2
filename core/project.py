"""Project class — owns scenes.json (read-only) and state.json (runtime, writable).

Schema separation (SPEC §5): scenes.json stays clean for the author; runtime
status (image/video/voice progress, warnings, selected_visual) lives in
state.json with atomic writes + rotating backups.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger as log

from core.paths import ProjectPaths
from core.schema import Scene, ScenesJson
from core.voice_mapping import VoiceMapping

STATE_VERSION = 1
BACKUP_KEEP = 5

StatusValue = Literal["pending", "generating", "ready", "failed"]
StateKey = Literal["image", "video", "voice"]
SelectedVisual = Literal["image", "video"]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _initial_scene_state() -> dict[str, Any]:
    return {
        "image": {
            "status": "pending",
            "path": None,
            "last_gen_at": None,
            "fail_reason": None,
        },
        "video": {
            "status": "pending",
            "path": None,
            "source_type": None,
            "last_gen_at": None,
            "fail_reason": None,
        },
        "voice": {
            "status": "pending",
            "path": None,
            "duration_sec": None,
        },
        "selected_visual": None,
        "warnings": [],
    }


class Project:
    """Load scenes.json + state.json for a project directory.

    Lifecycle:
        project = Project.load(Path("projects/morning_coffee"))
        project.update_scene_state("SCENE-01", "image", {"status": "ready", "path": "sources/pic1.jpg"})
        project.set_selected_visual("SCENE-01", "image")
        # state.json is persisted on every mutation (atomic write).
    """

    def __init__(self, paths: ProjectPaths, scenes_json: ScenesJson, state: dict[str, Any]):
        self.paths = paths
        self.scenes_json = scenes_json
        self.state = state
        self.voice_mapping: VoiceMapping | None = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, project_dir: Path) -> "Project":
        """Load a project from disk. Creates state.json on first run.

        Also auto-fills `Scene.effect` on scenes that don't carry one
        (alternates zoom_in/out for static visuals, no_effect for video_grok)
        and persists scenes.json if any defaults were filled in.
        """
        paths = ProjectPaths(project_dir)
        if not paths.scenes_json.exists():
            raise FileNotFoundError(f"Không tìm thấy scenes.json: {paths.scenes_json}")

        log.info(f"Đang load project: {paths.root.name}")
        scenes_json, raw_scenes_data = cls._load_scenes_with_raw(paths.scenes_json)

        if paths.state_json.exists():
            state = cls._load_state(paths.state_json)
            state = cls._reconcile(state, scenes_json)
        else:
            log.info("Chưa có state.json — khởi tạo mới")
            state = cls._build_initial_state(scenes_json)

        paths.ensure_dirs()
        project = cls(paths, scenes_json, state)
        # Auto-fill effect for any scene whose raw JSON didn't declare one.
        if cls._auto_fill_effects(project, raw_scenes_data):
            project.save_scenes_json()
            log.info("Auto-filled missing 'effect' fields → scenes.json saved")
        project._save_state_atomic()
        project._load_voice_mapping_if_present()
        return project

    @staticmethod
    def _load_scenes(path: Path) -> ScenesJson:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return ScenesJson.model_validate(data)

    @staticmethod
    def _load_scenes_with_raw(path: Path) -> tuple[ScenesJson, list[dict]]:
        """Load scenes.json + return raw per-scene dicts (pre-validation).

        Used for auto-fill: we need to know which scenes had no `effect`
        key in the source file (Pydantic's default substitution would hide it).
        """
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        raw = list(data.get("scenes", []))
        return ScenesJson.model_validate(data), raw

    @staticmethod
    def _auto_fill_effects(project: "Project", raw_scenes: list[dict]) -> bool:
        """Fill Scene.effect for entries whose source JSON didn't have it.

        Default policy:
            visual_type == "video_grok"     → effect = "no_effect"
            visual_type ∈ {image_grok, slideshow} → alternate zoom_in / zoom_out
        Returns True if any scene was changed (caller saves scenes.json).
        """
        had_effect_by_id: dict[str, bool] = {}
        for raw in raw_scenes:
            sid = raw.get("id")
            if sid:
                had_effect_by_id[sid] = "effect" in raw

        alternate_idx = 0
        changed = False
        for scene in project.scenes_json.scenes:
            if had_effect_by_id.get(scene.id, False):
                # Source declared effect; leave it alone.
                # Bump alternate counter only for static types so subsequent
                # auto-fills line up with the user's chosen rhythm.
                if scene.visual_type in ("image_grok", "slideshow"):
                    alternate_idx += 1
                continue

            if scene.visual_type == "video_grok":
                new_effect = "no_effect"
            elif scene.visual_type in ("image_grok", "slideshow"):
                new_effect = "zoom_in" if alternate_idx % 2 == 0 else "zoom_out"
                alternate_idx += 1
            else:
                new_effect = "no_effect"

            if scene.effect != new_effect:
                scene.effect = new_effect  # type: ignore[assignment]
                changed = True
        return changed

    @staticmethod
    def _load_state(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _build_initial_state(scenes_json: ScenesJson) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "updated_at": _now_iso(),
            "scenes": {scene.id: _initial_scene_state() for scene in scenes_json.scenes},
        }

    @staticmethod
    def _reconcile(state: dict[str, Any], scenes_json: ScenesJson) -> dict[str, Any]:
        """Add missing scene entries (scenes.json grew) and drop orphans."""
        scenes = state.setdefault("scenes", {})
        current_ids = {s.id for s in scenes_json.scenes}
        for scene in scenes_json.scenes:
            if scene.id not in scenes:
                log.warning(f"Scene mới '{scene.id}' — thêm vào state")
                scenes[scene.id] = _initial_scene_state()
        for stale in set(scenes.keys()) - current_ids:
            log.warning(f"Bỏ scene cũ khỏi state: '{stale}'")
            scenes.pop(stale)
        state.setdefault("version", STATE_VERSION)
        state["updated_at"] = _now_iso()
        return state

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def scenes(self) -> list[Scene]:
        return self.scenes_json.scenes

    def scene(self, scene_id: str) -> Scene:
        s = self.scenes_json.scene_by_id(scene_id)
        if s is None:
            raise KeyError(f"Không tìm thấy scene id: {scene_id}")
        return s

    def scene_index(self, scene_id: str) -> int:
        """1-based index of scene in scenes list (used for pic{N}.jpg, vid{N}.mp4)."""
        for i, s in enumerate(self.scenes_json.scenes, start=1):
            if s.id == scene_id:
                return i
        raise KeyError(f"Không tìm thấy scene id: {scene_id}")

    def get_scene_state(self, scene_id: str) -> dict[str, Any]:
        if scene_id not in self.state["scenes"]:
            raise KeyError(f"Scene chưa có trong state: {scene_id}")
        return self.state["scenes"][scene_id]

    # ------------------------------------------------------------------
    # Mutations (each one persists state.json atomically)
    # ------------------------------------------------------------------

    def update_scene_state(
        self,
        scene_id: str,
        key: StateKey,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge `patch` into state.scenes[scene_id][key] then persist.

        Example:
            project.update_scene_state(
                "SCENE-01", "image",
                {"status": "ready", "path": "sources/pic1.jpg",
                 "last_gen_at": iso_now()}
            )
        """
        scene_state = self.get_scene_state(scene_id)
        if key not in scene_state:
            raise KeyError(f"State key không hợp lệ: {key}")
        scene_state[key].update(patch)
        log.debug(f"State[{scene_id}].{key} ← {patch}")
        self._save_state_atomic()
        return scene_state[key]

    def set_selected_visual(self, scene_id: str, choice: SelectedVisual | None) -> None:
        scene_state = self.get_scene_state(scene_id)
        scene_state["selected_visual"] = choice
        log.info(f"Scene {scene_id}: chọn visual = {choice}")
        self._save_state_atomic()

    def add_warning(self, scene_id: str, code: str, msg: str) -> None:
        scene_state = self.get_scene_state(scene_id)
        scene_state.setdefault("warnings", []).append(
            {"code": code, "msg": msg, "ts": _now_iso()}
        )
        log.warning(f"Cảnh báo {scene_id} [{code}]: {msg}")
        self._save_state_atomic()

    def clear_warnings(self, scene_id: str, code: str | None = None) -> None:
        scene_state = self.get_scene_state(scene_id)
        if code is None:
            scene_state["warnings"] = []
        else:
            scene_state["warnings"] = [
                w for w in scene_state.get("warnings", []) if w.get("code") != code
            ]
        self._save_state_atomic()

    def update_scene_field(self, scene_id: str, field: str, value: Any) -> Scene:
        """Update one Scene field and atomic-save scenes.json. Re-validates."""
        return self.update_scene_fields(scene_id, {field: value})

    def update_scene_fields(self, scene_id: str, updates: dict[str, Any]) -> Scene:
        """Replace scene fields and persist scenes.json. Re-validates via Pydantic.

        Used by the prompt-editor dialog. If `visual_type` changes from a video
        type to a non-video type, callers should reset the video sub-state
        separately via reset_scene(scene_id, "video").
        """
        scene = self.scene(scene_id)
        merged = {**scene.model_dump(), **updates}
        new_scene = Scene.model_validate(merged)

        scenes = list(self.scenes_json.scenes)
        for i, s in enumerate(scenes):
            if s.id == scene_id:
                scenes[i] = new_scene
                break
        self.scenes_json = ScenesJson.model_validate(
            {**self.scenes_json.model_dump(), "scenes": [s.model_dump() for s in scenes]}
        )
        self.save_scenes_json()
        log.info(f"Đã cập nhật scene {scene_id}")
        return new_scene

    def save_scenes_json(self) -> None:
        """Atomic write of scenes.json (mirrors state.json pattern)."""
        target = self.paths.scenes_json
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.scenes_json.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, target)

    def reset_scene(self, scene_id: str, key: StateKey | None = None) -> None:
        """Reset image/video/voice for one scene, or the whole scene if key is None."""
        if key is None:
            self.state["scenes"][scene_id] = _initial_scene_state()
        else:
            initial = _initial_scene_state()
            self.state["scenes"][scene_id][key] = initial[key]
        self._save_state_atomic()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Public flush — call after batched in-place mutations."""
        self._save_state_atomic()

    def _load_voice_mapping_if_present(self) -> None:
        path = self.paths.voice_mapping_json
        if not path.exists():
            return
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            self.voice_mapping = VoiceMapping.model_validate(data)
            log.info(f"Loaded voice_mapping: {len(self.voice_mapping.voice_files)} files")
        except Exception as e:
            log.error(f"voice_mapping.json invalid: {e}")
            self.voice_mapping = None

    def save_voice_mapping(self, mapping: VoiceMapping) -> None:
        """Atomically write voice_mapping.json + cache on the project."""
        target = self.paths.voice_mapping_json
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(mapping.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, target)
        self.voice_mapping = mapping
        log.info(f"Saved voice_mapping → {target}")

    def _save_state_atomic(self) -> None:
        self.state["version"] = STATE_VERSION
        self.state["updated_at"] = _now_iso()

        target = self.paths.state_json
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            self._rotate_backup(target)

        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, target)

    def _rotate_backup(self, target: Path) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = target.with_name(f"{target.name}.bak.{ts}")
        try:
            shutil.copy2(target, backup)
        except OSError as e:
            log.warning(f"Không backup được state: {e}")
            return
        backups = sorted(
            target.parent.glob(f"{target.name}.bak.*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[BACKUP_KEEP:]:
            try:
                old.unlink()
            except OSError:
                pass
