"""Two-level voice matching orchestrator.

Per sprint_1 spec, this is the top-level entry point:

  1. Load + validate S5 (already done by s5_loader)
  2. Build beat timeline (already done by beat_timeline)
  3. Build master_voice.wav (already done by master_audio_builder)
  4. Whisper transcribe master → global words
  5. For each beat:
     - Filter words to beat window
     - Classify scenes voiced/silent (from scenes.json by id)
     - Single-scene beat shortcut
     - Match voiced scenes with flexible matcher (local cursor per beat)
     - Allocate silent scenes into resulting gaps
     - Emit beat_pause item if pause_after_sec > 0
  6. Validate:
     - No voiced scene marked silent
     - No negative durations
     - Per-beat coverage ≈ beat.voice_duration (±0.05s)
     - No global double-offset
  7. Emit:
     - voice_matching_timeline.json
     - voice_matching_diagnostics.json

Hard rules respected (spec §9.6 + §14.3):
  * `no_match` voiced scenes stay as `scene_type="voiced"` with status
    `"unmatched_voiced_scene"`. NEVER silently converted to silent.
  * Cursor is LOCAL per beat (reset at start of each beat). Global cursor
    only used by beat_timeline to compute beat offsets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger as log

from voice.beat_timeline import BeatTiming
from voice.flexible_matcher import find_match_in_beat, MATCH_THRESHOLD
from voice.master_whisper import (
    detect_double_offset,
    filter_words_by_beat,
)
from voice.silent_allocator import allocate_silent_block
from voice.voice_aligner import extract_subtitle_phrases


COVERAGE_TOLERANCE_SEC = 0.05         # spec §14.2
NEGATIVE_DURATION_TOLERANCE = 0.001


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TwoLevelResult:
    """Output of the orchestrator."""
    ok: bool
    timeline: dict                    # voice_matching_timeline.json content
    diagnostics: dict                 # voice_matching_diagnostics.json content
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-beat processing
# ---------------------------------------------------------------------------

def _classify_scene(scene: dict) -> str:
    """voiced if script has any non-whitespace chars, else silent (spec §8.2)."""
    return "voiced" if (scene.get("script") or "").strip() else "silent"


def _scene_visual_source(scene: dict) -> tuple[str, str]:
    """Per spec §2 / §7 step 2 resolve_visual_source.

    Image     → sources/{scene_id}.jpg
    Video     → sources/{scene_id}.mp4
    slideshow → sources/{scene_id}.mp4 (pre-rendered, treated as video)
    """
    scene_id = scene["id"]
    vt = (scene.get("visual_type") or "").lower()
    if vt == "image":
        return "image", f"sources/{scene_id}.jpg"
    if vt in ("video", "slideshow"):
        return "video", f"sources/{scene_id}.mp4"
    return "unknown", f"sources/{scene_id}.mp4"


def _build_voiced_item(
    scene: dict,
    beat: BeatTiming,
    match_result,
    subtitle_phrases: Optional[list[dict]] = None,
) -> dict:
    """Convert MatchResult into a timeline scene item (voiced)."""
    visual_type, visual_source = _scene_visual_source(scene)

    if match_result.matched:
        item = {
            "type": "scene",
            "scene_id": scene["id"],
            "beat_id": beat.beat_id,
            "scene_type": "voiced",
            "render_in": round(match_result.voice_in, 3),
            "render_out": round(match_result.voice_out, 3),
            "duration": round(match_result.voice_out - match_result.voice_in, 3),
            "voice_in": round(match_result.voice_in, 3),
            "voice_out": round(match_result.voice_out, 3),
            "design_duration": float(scene.get("duration") or 0),
            "visual_type": visual_type,
            "visual_source": visual_source,
            "match_method": match_result.method,
            "match_score": round(match_result.score / 100, 3),
            "word_start_index": match_result.word_start_index,
            "word_end_index": match_result.word_end_index,
            "subtitle_phrases": list(subtitle_phrases or []),
            "warnings": list(match_result.warnings),
        }
    else:
        # NEVER convert to silent (spec §9.6 + acceptance #13)
        item = {
            "type": "scene",
            "scene_id": scene["id"],
            "beat_id": beat.beat_id,
            "scene_type": "voiced",
            "status": "unmatched_voiced_scene",
            "render_in": None,
            "render_out": None,
            "duration": None,
            "voice_in": None,
            "voice_out": None,
            "design_duration": float(scene.get("duration") or 0),
            "visual_type": visual_type,
            "visual_source": visual_source,
            "match_method": "no_match",
            "match_score": round(match_result.score / 100, 3) if match_result.score else 0,
            "subtitle_phrases": [],
            "warnings": [
                "voiced_scene_not_matched_in_beat",
                *match_result.warnings,
            ],
        }
    return item


def _build_single_scene_beat_item(
    scene: dict,
    beat: BeatTiming,
    subtitle_phrases: Optional[list[dict]] = None,
) -> dict:
    """Spec §8.3: single voiced scene → full beat window."""
    visual_type, visual_source = _scene_visual_source(scene)
    return {
        "type": "scene",
        "scene_id": scene["id"],
        "beat_id": beat.beat_id,
        "scene_type": "voiced",
        "render_in": round(beat.voice_in, 3),
        "render_out": round(beat.voice_out, 3),
        "duration": round(beat.voice_out - beat.voice_in, 3),
        "voice_in": round(beat.voice_in, 3),
        "voice_out": round(beat.voice_out, 3),
        "design_duration": float(scene.get("duration") or 0),
        "visual_type": visual_type,
        "visual_source": visual_source,
        "match_method": "single_scene_beat",
        "match_score": 1.0,
        "subtitle_phrases": list(subtitle_phrases or []),
        "warnings": [],
    }


def _build_beat_pause_item(beat: BeatTiming) -> Optional[dict]:
    """Spec §12: emit explicit beat_pause item if pause_after_sec > 0."""
    if beat.pause_after_sec <= 0:
        return None
    return {
        "type": "beat_pause",
        "beat_id": beat.beat_id,
        "after_scene_id": beat.scene_ids[-1] if beat.scene_ids else None,
        "render_in": round(beat.pause_in, 3),
        "render_out": round(beat.pause_out, 3),
        "duration": round(beat.pause_after_sec, 3),
        "visual_policy": "freeze_tail",
        "audio_policy": "synthetic_silence_in_master_audio",
    }


def process_beat(
    beat: BeatTiming,
    scenes_in_beat: list[dict],
    beat_words: list[dict],
) -> tuple[list[dict], list[str]]:
    """Process one beat → list of timeline items + warnings.

    Returns:
        (items, warnings) where items includes voiced + silent scenes
        (NOT the beat_pause item — that's appended by the orchestrator).
    """
    warnings: list[str] = []

    # Pair scenes with their original index so we can preserve order
    scene_records = [
        {"scene": s, "type": _classify_scene(s), "idx": i}
        for i, s in enumerate(scenes_in_beat)
    ]

    voiced_scenes = [r for r in scene_records if r["type"] == "voiced"]
    silent_scenes = [r for r in scene_records if r["type"] == "silent"]

    n_voiced = len(voiced_scenes)
    n_silent = len(silent_scenes)

    # ---- Single-scene beat shortcut (spec §8.3) ----
    if len(scene_records) == 1:
        only = scene_records[0]
        if only["type"] == "voiced":
            subtitle_phrases = extract_subtitle_phrases(
                beat_words,
                beat.voice_in,
                beat.voice_out,
            )
            item = _build_single_scene_beat_item(
                only["scene"],
                beat,
                subtitle_phrases=subtitle_phrases,
            )
            return [item], warnings
        # Single silent scene → allocate over entire beat voice window
        items = allocate_silent_block(
            silent_scenes=[only["scene"]],
            gap_start=beat.voice_in,
            gap_end=beat.voice_out,
            beat_id=beat.beat_id,
        )
        return items, warnings

    # ---- Multi-scene beat ----
    voiced_items_by_idx: dict[int, dict] = {}
    voiced_match_records: list[dict] = []   # for silent allocation gap calc

    if n_voiced > 0:
        local_cursor = 0
        for rec in voiced_scenes:
            scene = rec["scene"]
            mr = find_match_in_beat(
                scene_id=scene["id"],
                scene_text=scene.get("script") or "",
                beat_words=beat_words,
                local_cursor=local_cursor,
            )
            subtitle_phrases = (
                extract_subtitle_phrases(beat_words, mr.voice_in, mr.voice_out)
                if mr.matched and mr.voice_in is not None and mr.voice_out is not None
                else []
            )
            item = _build_voiced_item(
                scene,
                beat,
                mr,
                subtitle_phrases=subtitle_phrases,
            )
            voiced_items_by_idx[rec["idx"]] = item

            voiced_match_records.append({
                "idx": rec["idx"],
                "matched": mr.matched,
                "voice_in": mr.voice_in,
                "voice_out": mr.voice_out,
            })

            # Advance LOCAL cursor only on successful match (spec §9.6)
            if mr.matched and mr.word_end_index is not None:
                local_cursor = mr.word_end_index + 1

    # ---- Allocate silent scenes into gaps between voiced ----
    silent_items_by_idx: dict[int, dict] = {}

    if n_silent > 0:
        # Group consecutive silents by original index, then for each block
        # find its surrounding voiced anchors (matched only) to define the gap.
        matched_voiced = [
            r for r in voiced_match_records if r["matched"]
        ]
        matched_by_idx = {r["idx"]: r for r in matched_voiced}

        # Build a sorted list of all matched voiced positions
        anchors_sorted = sorted(matched_voiced, key=lambda r: r["idx"])

        # Iterate silent blocks in scene order
        i = 0
        while i < len(scene_records):
            if scene_records[i]["type"] != "silent":
                i += 1
                continue
            # Collect consecutive silents
            block_start_i = i
            block_scenes: list[dict] = []
            while i < len(scene_records) and scene_records[i]["type"] == "silent":
                block_scenes.append(scene_records[i]["scene"])
                i += 1
            block_end_i = i - 1

            # Find surrounding matched voiced anchors by idx
            left_anchor = None
            for r in anchors_sorted:
                if r["idx"] < block_start_i:
                    left_anchor = r
                else:
                    break
            right_anchor = None
            for r in anchors_sorted:
                if r["idx"] > block_end_i:
                    right_anchor = r
                    break

            gap_start = (
                left_anchor["voice_out"] if left_anchor else beat.voice_in
            )
            gap_end = (
                right_anchor["voice_in"] if right_anchor else beat.voice_out
            )

            if gap_end < gap_start:
                # Voiced scenes overlap or are mis-ordered — fall back to
                # beat window so silents still appear somewhere
                warnings.append(
                    f"{beat.beat_id}: voiced anchors out of order around silent block "
                    f"[{block_start_i}..{block_end_i}], falling back to full beat window"
                )
                gap_start, gap_end = beat.voice_in, beat.voice_out

            allocated = allocate_silent_block(
                silent_scenes=block_scenes,
                gap_start=gap_start,
                gap_end=gap_end,
                beat_id=beat.beat_id,
            )

            # Re-attach original indices for ordering
            block_idx_iter = iter(range(block_start_i, block_end_i + 1))
            for item in allocated:
                silent_items_by_idx[next(block_idx_iter)] = item

    # ---- Combine in original scene order ----
    items: list[dict] = []
    for rec in scene_records:
        idx = rec["idx"]
        if idx in voiced_items_by_idx:
            items.append(voiced_items_by_idx[idx])
        elif idx in silent_items_by_idx:
            items.append(silent_items_by_idx[idx])

    # ---- Normalize: clamp overlaps to enforce strict ordering ----
    # The matcher allows BACKWARD_LOOKAHEAD_WORDS so the rescue path works,
    # but that can produce tiny render_in < prev.render_out overlaps when
    # the previous match was actually correct. Clamp cur.render_in forward
    # so timeline items never overlap. voice_in stays unchanged for
    # diagnostics; render_in is the timeline-display value.
    _normalize_overlaps(items)

    return items, warnings


def _normalize_overlaps(items: list[dict]) -> None:
    """Mutate items in place to enforce render_in >= previous render_out.

    Voiced item with matched=True: clamp render_in forward.
    If clamp would make render_out <= render_in (zero duration), keep
    a minimum 1-frame window (~0.033s @ 30fps).
    """
    MIN_CLIP_DURATION = 0.033  # ~1 frame @ 30fps
    prev_render_out: float | None = None

    for it in items:
        ri = it.get("render_in")
        ro = it.get("render_out")
        if ri is None or ro is None:
            continue
        if prev_render_out is not None and ri < prev_render_out:
            new_ri = prev_render_out
            new_ro = max(ro, new_ri + MIN_CLIP_DURATION)
            it["render_in"] = round(new_ri, 3)
            it["render_out"] = round(new_ro, 3)
            it["duration"] = round(new_ro - new_ri, 3)
            it.setdefault("warnings", []).append(
                f"render_in clamped +{new_ri - ri:.3f}s to avoid overlap"
            )
        prev_render_out = it["render_out"]


# ---------------------------------------------------------------------------
# Orchestrator (top level)
# ---------------------------------------------------------------------------

def build_timeline(
    beats: list[BeatTiming],
    scenes_by_id: dict[str, dict],
    whisper_words: list[dict],
    master_voice_path: Path,
    project_id: str = "unknown",
    fps: int = 30,
    width: int = 1920,
    height: int = 1080,
) -> TwoLevelResult:
    """Build voice_matching_timeline + diagnostics from M1 outputs + Whisper words.

    Args:
        beats: list[BeatTiming] from build_beat_timeline()
        scenes_by_id: dict[scene_id → scene dict from scenes.json]
        whisper_words: list[{word, start, end, source_file}] from
            transcribe_master_audio(); timestamps are GLOBAL on master.
        master_voice_path: path to master_voice.wav
        project_id / fps / width / height: passed through into the
            timeline JSON output for downstream renderers.

    Returns:
        TwoLevelResult with timeline + diagnostics dicts (also writable to
        disk by caller via json.dump).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Sanity: detect double-offset issue early
    dbo = detect_double_offset(whisper_words, beats)
    if dbo:
        warnings.append(dbo)
        log.warning(dbo)

    timeline_items: list[dict] = []
    per_beat_diag: list[dict] = []
    unmatched_scene_count = 0
    voiced_scene_count = 0
    silent_scene_count = 0
    beat_pause_count = 0

    for beat in beats:
        # Resolve scenes in this beat (preserve order from S5)
        beat_scenes = []
        for sid in beat.scene_ids:
            scene = scenes_by_id.get(sid)
            if scene is None:
                errors.append(f"{beat.beat_id}: scene {sid!r} not in scenes.json")
                continue
            beat_scenes.append(scene)

        if not beat_scenes:
            warnings.append(f"{beat.beat_id}: no resolvable scenes — beat skipped")
            # Still emit pause item if any
            pause_item = _build_beat_pause_item(beat)
            if pause_item:
                timeline_items.append(pause_item)
                beat_pause_count += 1
            per_beat_diag.append({
                "beat_id": beat.beat_id,
                "voice_duration": round(beat.measured_duration, 3),
                "pause_after_sec": round(beat.pause_after_sec, 3),
                "scene_count": 0,
                "matched_scene_count": 0,
                "silent_scene_count": 0,
                "coverage_delta_sec": 0.0,
                "warnings": ["no_resolvable_scenes"],
            })
            continue

        # Filter whisper words to this beat
        beat_words = filter_words_by_beat(whisper_words, beat)
        if not beat_words:
            warnings.append(
                f"{beat.beat_id}: Whisper produced no words in window "
                f"[{beat.voice_in:.2f}, {beat.voice_out:.2f}]"
            )

        items, w = process_beat(beat, beat_scenes, beat_words)
        warnings.extend(w)
        timeline_items.extend(items)

        # Pause item after this beat's scenes
        pause_item = _build_beat_pause_item(beat)
        if pause_item:
            timeline_items.append(pause_item)
            beat_pause_count += 1

        # Per-beat diagnostics
        matched = sum(
            1 for it in items
            if it.get("scene_type") == "voiced"
            and it.get("status") != "unmatched_voiced_scene"
        )
        silent = sum(1 for it in items if it.get("scene_type") == "silent")
        unmatched = sum(
            1 for it in items if it.get("status") == "unmatched_voiced_scene"
        )

        voiced_scene_count += matched + unmatched
        silent_scene_count += silent
        unmatched_scene_count += unmatched

        # Coverage delta: sum of scene durations vs beat voice duration
        scene_dur_sum = sum(
            it.get("duration") or 0
            for it in items
            if it.get("duration") is not None
        )
        coverage_delta = scene_dur_sum - beat.measured_duration

        per_beat_warnings = []
        if abs(coverage_delta) > COVERAGE_TOLERANCE_SEC and unmatched == 0:
            per_beat_warnings.append(
                f"coverage_delta {coverage_delta:+.3f}s exceeds ±{COVERAGE_TOLERANCE_SEC}s"
            )

        per_beat_diag.append({
            "beat_id": beat.beat_id,
            "voice_duration": round(beat.measured_duration, 3),
            "pause_after_sec": round(beat.pause_after_sec, 3),
            "scene_count": len(beat_scenes),
            "matched_scene_count": matched,
            "silent_scene_count": silent,
            "unmatched_voiced_scene_count": unmatched,
            "coverage_delta_sec": round(coverage_delta, 3),
            "warnings": per_beat_warnings,
        })

    # ---- Final cross-beat normalization ----
    # process_beat() only clamps within its own beat. Cross-beat boundaries
    # (e.g. beat_pause vs next beat's first scene) can still micro-overlap
    # because ffprobe rounding differs from Whisper word boundaries by a few
    # milliseconds. Do one more pass over the full timeline.
    _normalize_overlaps(timeline_items)

    # ---- Global validations (spec §14) ----
    # 14.3: no voiced scene marked silent — already enforced by scene_type
    # logic, but double-check
    for it in timeline_items:
        if it.get("type") != "scene":
            continue
        sid = it.get("scene_id")
        scene = scenes_by_id.get(sid, {})
        has_script = bool((scene.get("script") or "").strip())
        if has_script and it.get("scene_type") == "silent":
            errors.append(f"{sid}: voiced scene incorrectly marked as silent")

    # 14.4: no negative durations
    for it in timeline_items:
        ri = it.get("render_in")
        ro = it.get("render_out")
        if ri is not None and ro is not None and ro < ri - NEGATIVE_DURATION_TOLERANCE:
            errors.append(
                f"{it.get('scene_id') or it.get('beat_id')}: negative duration "
                f"{ri:.3f} → {ro:.3f}"
            )

    # 14.5: no major overlap (between consecutive items with non-null windows)
    overlap_warns = 0
    prev_end = None
    for it in timeline_items:
        ri = it.get("render_in")
        ro = it.get("render_out")
        if ri is None or ro is None:
            continue
        if prev_end is not None and ri < prev_end - 0.03:
            overlap_warns += 1
        prev_end = ro
    if overlap_warns:
        warnings.append(f"timeline_overlap: {overlap_warns} consecutive overlaps detected")

    # ---- Build outputs ----
    total_duration = beats[-1].pause_out if beats else 0.0

    timeline = {
        "project_id": project_id,
        "fps": fps,
        "width": width,
        "height": height,
        "audio_master": str(master_voice_path).replace("\\", "/"),
        "total_duration": round(total_duration, 3),
        "config": {
            "match_threshold": MATCH_THRESHOLD,
            "boundary_tolerance_sec": 0.05,
            "min_visible_clip_sec": 0.10,
            "extreme_silent_compress_ratio": 0.50,
            "extreme_silent_stretch_ratio": 2.00,
            "whisper_mode": "master_audio",
            "timestamp_mode": "global",
            "scene_silence_policy": "allocate_existing_gap",
            "beat_pause_policy": "synthetic_silence",
            "single_scene_beat_policy": "full_beat_window",
        },
        "beats": [b.to_dict() for b in beats],
        "timeline": timeline_items,
    }

    diagnostics = {
        "summary": {
            "beats": len(beats),
            "scenes": voiced_scene_count + silent_scene_count,
            "voiced_scenes": voiced_scene_count,
            "silent_scenes": silent_scene_count,
            "unmatched_voiced_scenes": unmatched_scene_count,
            "beat_pauses": beat_pause_count,
            "total_duration": round(total_duration, 3),
        },
        "warnings": warnings,
        "errors": errors,
        "per_beat": per_beat_diag,
    }

    ok = not errors
    if ok:
        log.info(
            f"Timeline built: {len(timeline_items)} items "
            f"({voiced_scene_count} voiced, {silent_scene_count} silent, "
            f"{unmatched_scene_count} unmatched, {beat_pause_count} pauses)"
        )
    else:
        log.error(f"Timeline build FAILED: {len(errors)} error(s)")

    return TwoLevelResult(
        ok=ok,
        timeline=timeline,
        diagnostics=diagnostics,
        errors=errors,
        warnings=warnings,
    )


def save_outputs(
    result: TwoLevelResult,
    timeline_path: Path,
    diagnostics_path: Path,
) -> None:
    """Atomically write timeline + diagnostics JSON files."""
    for path, data in [
        (timeline_path, result.timeline),
        (diagnostics_path, result.diagnostics),
    ]:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        log.info(f"Saved {path.name} ({len(data.get('timeline', data.get('warnings', [])))} items)")
