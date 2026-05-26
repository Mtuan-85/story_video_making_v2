"""S5 loader: parse the per-beat narration JSON (e.g. Naomi2_S5.json).

S5 is the source-of-truth beat file (S6 adds emotional tags for TTS only —
do NOT use S6 for matching).

Schema (validated):
    [
      {
        "beat_id": "beat-01",
        "beat_role": "hook",
        "emotion": "...",
        "script": "raw narration text",
        "pause_after_sec": 0.5,
        "scenes": ["SCENE-01", "SCENE-02", "SCENE-03"]
      },
      ...
    ]

Validation rules (per sprint_1 spec §7 Step 1):
- S5 JSON is a non-empty list of dicts.
- Each beat has beat_id + scenes[] + pause_after_sec.
- Every beat.scenes[] entry exists in scenes.json (no missing refs).
- No duplicate scene refs across all beats.
- Beat scene order matches scenes.json scene order.
- Per beat: voice file beat-XX.mp3 exists.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger as log


# Naming: beat-01 in JSON, beat-01.mp3 on disk (dash convention)
_BEAT_ID_RE = re.compile(r"^beat[-_](\d+)$", re.IGNORECASE)


@dataclass
class Beat:
    """One narration beat with its audio file + scene refs."""
    beat_id: str                    # canonical: "beat-01" (dash)
    beat_index: int                 # 1-based index parsed from id
    voice_file: Path                # absolute path to beat-XX.mp3
    script: str                     # raw narration (NO emotional tags)
    pause_after_sec: float          # silence injected AFTER this beat in master
    scene_ids: list[str]            # ordered scene refs into scenes.json
    beat_role: Optional[str] = None # e.g. "hook", "bumper"
    emotion: Optional[str] = None   # e.g. "warm_intimate"
    raw: dict = field(default_factory=dict)  # original JSON entry

    def to_dict(self) -> dict:
        return {
            "beat_id": self.beat_id,
            "beat_index": self.beat_index,
            "voice_file": str(self.voice_file),
            "script": self.script,
            "pause_after_sec": self.pause_after_sec,
            "scene_ids": list(self.scene_ids),
            "beat_role": self.beat_role,
            "emotion": self.emotion,
        }


@dataclass
class S5ValidationResult:
    """Per-validation report so caller can show clear errors."""
    ok: bool
    beats: list[Beat]
    errors: list[str]
    warnings: list[str]
    ref_count: int                  # total scene refs across all beats
    scene_count: int                # scenes in scenes.json
    missing_mp3: list[str]          # beat_ids whose mp3 not found
    unreferenced_scenes: list[str]  # scenes.json entries no beat claims


def _normalize_beat_id(raw_id: str) -> tuple[str, int]:
    """Return (canonical_id, index). Accepts beat_01 OR beat-01.

    Canonical form: 'beat-01' (dash, zero-padded width=2).
    """
    m = _BEAT_ID_RE.match(raw_id.strip())
    if not m:
        raise ValueError(f"Invalid beat_id format: {raw_id!r} (expected beat-NN or beat_NN)")
    idx = int(m.group(1))
    return f"beat-{idx:02d}", idx


def _candidate_voice_dirs(voice_dir: Path) -> list[Path]:
    voice_dir = Path(voice_dir)
    project_root = voice_dir.parent
    dirs = [
        voice_dir / "source" / "s6",
        voice_dir,
    ]
    dirs.extend(sorted(project_root.glob("*_S6_voice")))
    return dirs


def _find_voice_file(voice_dir: Path, beat_index: int) -> Optional[Path]:
    """Try common naming patterns for the per-beat MP3."""
    candidates = [
        f"beat-{beat_index:02d}.mp3",
        f"beat-{beat_index}.mp3",
        f"beat_{beat_index:02d}.mp3",
        f"beat_{beat_index}.mp3",
    ]
    for directory in _candidate_voice_dirs(voice_dir):
        for name in candidates:
            p = directory / name
            if p.exists():
                return p.resolve()
    return None


def load_and_validate_s5(
    s5_path: Path,
    scenes_json_path: Path,
    voice_dir: Path,
) -> S5ValidationResult:
    """Load + validate S5. Returns S5ValidationResult.

    Caller decides whether to proceed when result.ok == False.

    Args:
        s5_path: path to <stem>_S5.json
        scenes_json_path: path to <stem>_edited.json (or <stem>.json)
        voice_dir: folder containing beat-XX.mp3 files
    """
    errors: list[str] = []
    warnings: list[str] = []
    beats: list[Beat] = []

    # ---- Load S5 ----
    if not s5_path.exists():
        return S5ValidationResult(
            ok=False, beats=[], errors=[f"S5 file not found: {s5_path}"],
            warnings=[], ref_count=0, scene_count=0,
            missing_mp3=[], unreferenced_scenes=[],
        )

    try:
        raw_data = json.loads(s5_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return S5ValidationResult(
            ok=False, beats=[], errors=[f"S5 JSON invalid: {e}"],
            warnings=[], ref_count=0, scene_count=0,
            missing_mp3=[], unreferenced_scenes=[],
        )

    if not isinstance(raw_data, list) or not raw_data:
        return S5ValidationResult(
            ok=False, beats=[], errors=["S5 must be a non-empty list"],
            warnings=[], ref_count=0, scene_count=0,
            missing_mp3=[], unreferenced_scenes=[],
        )

    # ---- Load scenes.json ----
    if not scenes_json_path.exists():
        errors.append(f"Scenes JSON not found: {scenes_json_path}")
        return S5ValidationResult(
            ok=False, beats=[], errors=errors,
            warnings=warnings, ref_count=0, scene_count=0,
            missing_mp3=[], unreferenced_scenes=[],
        )

    scenes_data = json.loads(scenes_json_path.read_text(encoding="utf-8"))
    if isinstance(scenes_data, dict) and "scenes" in scenes_data:
        scenes_list = scenes_data["scenes"]
    elif isinstance(scenes_data, list):
        scenes_list = scenes_data
    else:
        errors.append("Scenes JSON has unexpected structure")
        return S5ValidationResult(
            ok=False, beats=[], errors=errors,
            warnings=warnings, ref_count=0, scene_count=0,
            missing_mp3=[], unreferenced_scenes=[],
        )

    scene_order = {s["id"]: i for i, s in enumerate(scenes_list)}
    scene_ids_set = set(scene_order)

    # ---- Parse + validate per beat ----
    missing_mp3: list[str] = []
    all_refs: list[str] = []
    seen_beat_ids: set[str] = set()

    for i, entry in enumerate(raw_data):
        if not isinstance(entry, dict):
            errors.append(f"Beat #{i}: not a dict")
            continue

        raw_id = entry.get("beat_id")
        if not raw_id:
            errors.append(f"Beat #{i}: missing beat_id")
            continue

        try:
            beat_id, beat_idx = _normalize_beat_id(raw_id)
        except ValueError as e:
            errors.append(f"Beat #{i}: {e}")
            continue

        if beat_id in seen_beat_ids:
            errors.append(f"Beat {beat_id}: duplicate beat_id")
            continue
        seen_beat_ids.add(beat_id)

        # Required fields
        scenes_refs = entry.get("scenes") or []
        if not isinstance(scenes_refs, list):
            errors.append(f"Beat {beat_id}: scenes must be a list")
            continue
        if not scenes_refs:
            warnings.append(f"Beat {beat_id}: empty scenes[] (no visual mapping)")

        script = (entry.get("script") or "").strip()
        if not script:
            warnings.append(f"Beat {beat_id}: empty script")

        pause = entry.get("pause_after_sec")
        if pause is None:
            warnings.append(f"Beat {beat_id}: missing pause_after_sec (defaulting 0)")
            pause = 0.0
        try:
            pause = float(pause)
        except (TypeError, ValueError):
            errors.append(f"Beat {beat_id}: pause_after_sec not numeric ({pause!r})")
            continue
        if pause < 0:
            errors.append(f"Beat {beat_id}: pause_after_sec negative ({pause})")
            continue

        # Voice file
        voice_path = _find_voice_file(voice_dir, beat_idx)
        if voice_path is None:
            missing_mp3.append(beat_id)
            errors.append(f"Beat {beat_id}: voice file not found in {voice_dir}")
            continue

        # Scene ref validity (per-beat) — accumulate before global checks
        for sid in scenes_refs:
            all_refs.append(sid)
            if sid not in scene_ids_set:
                errors.append(f"Beat {beat_id}: references unknown scene {sid!r}")

        beats.append(Beat(
            beat_id=beat_id,
            beat_index=beat_idx,
            voice_file=voice_path,
            script=script,
            pause_after_sec=pause,
            scene_ids=list(scenes_refs),
            beat_role=entry.get("beat_role"),
            emotion=entry.get("emotion"),
            raw=entry,
        ))

    # ---- Global checks across beats ----
    # Duplicates
    duplicates = sorted({sid for sid in all_refs if all_refs.count(sid) > 1})
    if duplicates:
        errors.append(f"Scene refs duplicated across beats: {duplicates[:10]}")

    # Ordering (refs must follow scene order)
    ref_positions = [scene_order[r] for r in all_refs if r in scene_order]
    if ref_positions != sorted(ref_positions):
        errors.append("Scene refs across beats are not in scenes.json order")

    # Unreferenced scenes (warning only — some scenes may be visual-only)
    unreferenced = [sid for sid in scene_ids_set if sid not in set(all_refs)]
    if unreferenced:
        warnings.append(
            f"{len(unreferenced)} scene(s) in scenes.json not referenced by any beat "
            f"(e.g. {unreferenced[:3]}) — they will not get voice timing"
        )

    # Beat ordering by index
    seen_idx = [b.beat_index for b in beats]
    if seen_idx != sorted(seen_idx):
        warnings.append("Beats are not in ascending index order — reordering")
        beats.sort(key=lambda b: b.beat_index)

    ok = not errors
    if ok:
        log.info(
            f"S5 loaded: {len(beats)} beats, {len(all_refs)} scene refs, "
            f"{len(scenes_list)} scenes total. Warnings: {len(warnings)}"
        )
    else:
        log.error(f"S5 validation FAILED: {len(errors)} error(s)")

    return S5ValidationResult(
        ok=ok,
        beats=beats,
        errors=errors,
        warnings=warnings,
        ref_count=len(all_refs),
        scene_count=len(scenes_list),
        missing_mp3=missing_mp3,
        unreferenced_scenes=unreferenced,
    )
