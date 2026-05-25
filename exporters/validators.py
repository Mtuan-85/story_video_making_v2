"""Pre-export validation for the Kdenlive exporter.

Per Sprint 2 §16: catch schema/timing problems BEFORE we write XML so the
user sees a clean error instead of a corrupt .kdenlive file.

Checks:
  - timeline JSON has required keys
  - audio_master file exists
  - audio file duration ≈ total_duration (±0.05s or ±1 frame)
  - each scene/beat_pause item has render_in/render_out (or is unmatched)
  - render_out > render_in (no negative/zero durations after rounding)
  - no consecutive overlaps > 0.05s
  - max(render_out) ≈ total_duration (±0.05s)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


COVERAGE_TOLERANCE_SEC = 0.05
OVERLAP_TOLERANCE_SEC = 0.05


@dataclass
class ValidationReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    out = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {out.stderr}")
    return float((out.stdout or "0").strip())


def validate_timeline_for_export(
    timeline: dict,
    fps: int = 30,
    strict_no_match: bool = False,
) -> ValidationReport:
    """Validate `voice_matching_timeline.json` shape + timings.

    Args:
        timeline: parsed JSON dict
        fps: project fps (for tolerance calc)
        strict_no_match: if True, any unmatched_voiced_scene becomes an error.
            Spec §14.6 — default False means we warn but allow export.

    Returns:
        ValidationReport — caller checks .ok before exporting.
    """
    report = ValidationReport()

    # 1. Schema
    for key in ("audio_master", "total_duration", "timeline"):
        if key not in timeline:
            report.fail(f"timeline JSON missing key: {key!r}")

    if not report.ok:
        return report

    items = timeline["timeline"]
    if not isinstance(items, list):
        report.fail("timeline.timeline must be a list")
        return report

    # 2. Audio master existence + duration
    master_path = Path(timeline["audio_master"])
    if not master_path.is_absolute():
        # Try to resolve relative to whatever (caller passes absolute usually)
        pass

    if not master_path.exists():
        report.fail(f"audio_master file not found: {master_path}")
    else:
        try:
            audio_dur = _ffprobe_duration(master_path)
        except Exception as e:
            report.fail(f"ffprobe failed for audio_master: {e}")
        else:
            total_dur = float(timeline.get("total_duration") or 0)
            tol = max(COVERAGE_TOLERANCE_SEC, 1.0 / max(1, fps))
            if abs(audio_dur - total_dur) > tol:
                report.warn(
                    f"audio duration {audio_dur:.3f}s vs total_duration {total_dur:.3f}s "
                    f"differs by {audio_dur - total_dur:+.3f}s (tolerance ±{tol:.3f}s)"
                )

    # 3. Per-item validation
    has_anything_renderable = False
    timeline_max_out = 0.0
    prev_end: float | None = None
    overlap_count = 0
    unmatched_count = 0

    for it in items:
        itype = it.get("type")
        if itype not in ("scene", "beat_pause"):
            continue

        sid = it.get("scene_id") or it.get("beat_id") or "?"
        ri = it.get("render_in")
        ro = it.get("render_out")

        # Unmatched voiced scenes have render_in/out = None
        if it.get("status") == "unmatched_voiced_scene" or ri is None or ro is None:
            unmatched_count += 1
            if strict_no_match:
                report.fail(f"{sid}: unmatched voiced scene (strict mode)")
            else:
                report.warn(f"{sid}: unmatched — skipped from V1 (timeline has gap)")
            continue

        if ro <= ri:
            report.fail(f"{sid}: render_out <= render_in ({ri:.3f} → {ro:.3f})")
            continue

        # Min clip length check (1 frame)
        if (ro - ri) * fps < 1.0:
            report.warn(f"{sid}: clip shorter than 1 frame ({ro-ri:.3f}s @ {fps}fps)")

        if prev_end is not None and ri < prev_end - OVERLAP_TOLERANCE_SEC:
            overlap_count += 1
            report.warn(
                f"overlap: prev ends {prev_end:.3f}, {sid} starts {ri:.3f} "
                f"(overlap {prev_end-ri:.3f}s)"
            )

        prev_end = ro
        timeline_max_out = max(timeline_max_out, ro)
        has_anything_renderable = True

    if not has_anything_renderable:
        report.fail("Timeline has no renderable items (all unmatched/empty)")

    # 4. Timeline end matches total_duration
    total_dur = float(timeline.get("total_duration") or 0)
    tol_end = max(COVERAGE_TOLERANCE_SEC, 1.0 / max(1, fps))
    if has_anything_renderable and abs(timeline_max_out - total_dur) > tol_end:
        report.warn(
            f"timeline_end {timeline_max_out:.3f}s vs total_duration {total_dur:.3f}s "
            f"differs by {timeline_max_out - total_dur:+.3f}s"
        )

    if overlap_count:
        report.warn(f"{overlap_count} timeline overlap(s) detected — clips may stack")
    if unmatched_count:
        report.warn(f"{unmatched_count} unmatched voiced scene(s) skipped")

    return report
