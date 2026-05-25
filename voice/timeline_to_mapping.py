"""Adapter: voice_matching_timeline.json (Sprint 1) → VoiceMapping (legacy v4.0).

Sprint 1's timeline JSON and the legacy `voice_mapping.json` describe the
same alignment outcome with different schemas. The render pipeline + ASS
generator still consume `VoiceMapping`, so we provide a one-way adapter.

Mapping notes:
  - voice_files: a single entry pointing at master_voice.wav (because
    Sprint 1 concats beats into ONE master file). The render's voice
    slicer uses concat+atrim with global timestamps — passing one file is
    fine; the concat demuxer just streams that single source.
  - scenes: one SceneVoiceAssignment per timeline 'scene' item.
    Unmatched voiced scenes get is_silent=False with voice_in=voice_out
    so the renderer falls back to design duration / silence audio.
  - subtitle_phrases: NOT populated by Sprint 1 (phrase extraction was a
    Plan-D feature). Render still works — ASS file is empty and the
    libass burn step is a no-op (`apply_ass_subtitle` falls back to copy
    when ass_path is missing/empty).
  - freeze_pause_after: derived from beat_pause items. For each scene
    that ends a beat (last scene_id in beat.scenes), freeze_pause_after =
    beat.pause_after_sec. Other scenes get 0 (silent gaps inside a beat
    are handled by silent scene allocation, not freeze).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger as log

from core.voice_mapping import (
    SceneVoiceAssignment,
    VoiceFileMeta,
    VoiceMapping,
    VoiceMappingStats,
)


def timeline_to_voice_mapping(timeline_path: Path) -> VoiceMapping:
    """Convert Sprint 1 timeline JSON into a VoiceMapping (v4.0 shape).

    Args:
        timeline_path: voice_matching_timeline.json file

    Returns:
        VoiceMapping ready for project.save_voice_mapping().

    Raises:
        FileNotFoundError / RuntimeError on read/schema issues.
    """
    timeline_path = Path(timeline_path)
    if not timeline_path.exists():
        raise FileNotFoundError(f"Timeline JSON not found: {timeline_path}")

    data = json.loads(timeline_path.read_text(encoding="utf-8"))
    beats = data.get("beats") or []
    timeline_items = data.get("timeline") or []
    total_duration = float(data.get("total_duration") or 0)
    audio_master_str = data.get("audio_master") or ""
    audio_master_name = Path(audio_master_str).name or "master_voice.wav"

    # ---- voice_files: one entry for master_voice.wav ----
    voice_files = [
        VoiceFileMeta(
            file=audio_master_name,
            duration=total_duration,
            offset=0.0,
        )
    ]

    # ---- Build a scene_id → pause_after_sec lookup ----
    # A beat's last scene "owns" that beat's pause.
    pause_for_scene: dict[str, float] = {}
    for beat in beats:
        scene_ids = beat.get("scene_ids") or []
        pause_sec = float(beat.get("pause_after_sec") or 0)
        if scene_ids and pause_sec > 0:
            pause_for_scene[scene_ids[-1]] = pause_sec

    # ---- scenes: walk timeline 'scene' items in order ----
    scenes: list[SceneVoiceAssignment] = []
    seen_ids: set[str] = set()
    deterministic_pass = 0
    silent_count = 0
    unmatched_count = 0
    llm_fallback_count = 0

    for it in timeline_items:
        if it.get("type") != "scene":
            continue
        sid = it.get("scene_id")
        if not sid or sid in seen_ids:
            continue
        seen_ids.add(sid)

        scene_type = it.get("scene_type") or "voiced"
        is_unmatched = it.get("status") == "unmatched_voiced_scene"
        is_silent = (scene_type == "silent")

        if is_unmatched:
            # Voiced scene that the matcher couldn't anchor. Render falls
            # back to design duration by passing voice_in==voice_out=0
            # plus render_mode=design.
            scenes.append(SceneVoiceAssignment(
                id=sid,
                voice_in=0.0,
                voice_out=0.0,
                duration_original=float(it.get("design_duration") or 0),
                duration_adjusted=float(it.get("design_duration") or 0),
                is_silent=False,
                method="no_match",
                score=float(it.get("match_score") or 0) * 100 if it.get("match_score") else None,
                matched_text=None,
                subtitle_phrases=[],
                warning="voiced_scene_not_matched_in_beat",
                render_mode="design",
                render_duration=float(it.get("design_duration") or 0),
                freeze_pause_after=0.0,
            ))
            unmatched_count += 1
            continue

        if is_silent:
            scenes.append(SceneVoiceAssignment(
                id=sid,
                voice_in=None,
                voice_out=None,
                duration_original=float(it.get("design_duration") or 0),
                duration_adjusted=float(it.get("duration") or 0),
                is_silent=True,
                method="gap_allocated",
                subtitle_phrases=[],
                render_mode="voice",
                render_duration=float(it.get("duration") or 0),
                freeze_pause_after=pause_for_scene.get(sid, 0.0),
            ))
            silent_count += 1
            continue

        # Voiced + matched
        voice_in = float(it.get("voice_in") or 0)
        voice_out = float(it.get("voice_out") or 0)
        method = it.get("match_method") or "deterministic"
        # Sprint 1's match_score is 0-1; legacy uses 0-100
        score = float(it.get("match_score") or 0) * 100 if it.get("match_score") is not None else None

        scenes.append(SceneVoiceAssignment(
            id=sid,
            voice_in=voice_in,
            voice_out=voice_out,
            duration_original=float(it.get("design_duration") or 0),
            duration_adjusted=max(0.0, voice_out - voice_in),
            is_silent=False,
            method=method,
            score=score,
            matched_text=None,  # not stored in Sprint 1 timeline
            subtitle_phrases=[],  # see module docstring
            render_mode="voice",
            render_duration=max(0.0, voice_out - voice_in),
            freeze_pause_after=pause_for_scene.get(sid, 0.0),
        ))

        if method.startswith("llm"):
            llm_fallback_count += 1
        else:
            deterministic_pass += 1

    stats = VoiceMappingStats(
        total_scenes=len(scenes),
        deterministic_pass=deterministic_pass,
        deterministic_fail_need_fallback=unmatched_count,
        silent=silent_count,
        no_match=unmatched_count,
        llm_fallback_count=llm_fallback_count,
    )

    mapping = VoiceMapping(
        version="4.0",
        generated_at=datetime.now().isoformat(timespec="seconds"),
        voice_files=voice_files,
        total_voice_duration=total_duration,
        scenes=scenes,
        stats=stats,
    )

    log.info(
        f"timeline → voice_mapping: {len(scenes)} scenes "
        f"({deterministic_pass} matched, {silent_count} silent, "
        f"{unmatched_count} unmatched)"
    )
    return mapping
