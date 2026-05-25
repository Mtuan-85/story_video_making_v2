"""Allocate silent scenes into available gaps WITHIN their beat.

Per sprint_1 §11: silent scenes (empty script) are NOT word-matched.
They consume only existing voice gaps inside the beat, never the beat
pause and never gaps from other beats.

Allocation rules:
  * Between two voiced scenes A, B: gap = [A.voice_out, B.voice_in]
  * Before first voiced scene F: gap = [beat.voice_in, F.voice_in]
  * After last voiced scene L: gap = [L.voice_out, beat.voice_out]
  * Beat with only silent scenes: gap = [beat.voice_in, beat.voice_out]

Distribution within a gap: proportional to design duration of each
silent scene in the block. If all silents have design=0, split evenly.

Extreme scaling warnings (per spec §4 + §11.5):
  * scale_ratio < 0.50 → "silent_scene_compressed_too_much"
  * scale_ratio > 2.00 → "silent_scene_stretched_too_much"
"""

from __future__ import annotations

from typing import Optional


COMPRESS_RATIO_WARN = 0.50
STRETCH_RATIO_WARN = 2.00
MIN_VISIBLE_CLIP_SEC = 0.10           # min duration before flagging too-short


def allocate_silent_block(
    silent_scenes: list[dict],
    gap_start: float,
    gap_end: float,
    beat_id: str,
) -> list[dict]:
    """Distribute a list of silent scenes across [gap_start, gap_end].

    Returns one timeline-item dict per silent scene (spec §6.4 schema).
    Each item carries render_in/render_out + scale_ratio + warnings.

    `silent_scenes` items must contain at least `id` and `duration`.
    """
    if not silent_scenes:
        return []

    gap_duration = max(0.0, gap_end - gap_start)
    n = len(silent_scenes)

    # Sum of design durations (fall back to even split if all zero)
    design_total = sum(max(0.0, float(s.get("duration") or 0.0)) for s in silent_scenes)

    if design_total <= 0 or gap_duration <= 0:
        # Even split — silent scenes get equal portion of whatever's available
        per_scene = gap_duration / n if n else 0
        durations = [per_scene] * n
    else:
        ratio = gap_duration / design_total
        durations = [
            max(0.0, float(s.get("duration") or 0.0)) * ratio
            for s in silent_scenes
        ]

    items: list[dict] = []
    cursor = gap_start

    for scene, dur in zip(silent_scenes, durations):
        design_dur = max(0.0, float(scene.get("duration") or 0.0))
        warnings: list[str] = []

        scale_ratio: Optional[float] = None
        if design_dur > 0:
            scale_ratio = dur / design_dur
            if scale_ratio < COMPRESS_RATIO_WARN:
                warnings.append("silent_scene_compressed_too_much")
            elif scale_ratio > STRETCH_RATIO_WARN:
                warnings.append("silent_scene_stretched_too_much")

        if dur < MIN_VISIBLE_CLIP_SEC:
            warnings.append("silent_scene_below_min_visible")

        items.append({
            "type": "scene",
            "scene_id": scene["id"],
            "beat_id": beat_id,
            "scene_type": "silent",
            "render_in": round(cursor, 3),
            "render_out": round(cursor + dur, 3),
            "duration": round(dur, 3),
            "voice_in": None,
            "voice_out": None,
            "design_duration": round(design_dur, 3),
            "visual_type": scene.get("visual_type"),
            "visual_source": scene.get("visual_source"),
            "scale_ratio": round(scale_ratio, 3) if scale_ratio is not None else None,
            "match_method": "gap_allocated",
            "warnings": warnings,
        })
        cursor += dur

    return items
