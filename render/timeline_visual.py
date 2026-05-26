"""Render visual-only video from voice_matching_timeline.json."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from render.assemble import assemble_concat
from render.visual_fit import FPS, build_visual_filter_with_fit
from workers.process_registry import run_tracked

_STATIC_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class TimelineVisualSegment:
    kind: str
    scene_id: str
    duration: float


@dataclass(frozen=True)
class _TimelineRenderJob:
    segment: TimelineVisualSegment
    duration: float
    freeze_only: bool


def build_timeline_visual_segments(timeline: dict) -> list[TimelineVisualSegment]:
    """Build contiguous visual segments, inserting freeze gaps between items."""
    segments: list[TimelineVisualSegment] = []
    prev_out: float | None = None
    prev_scene_id: str | None = None

    for item in timeline.get("timeline") or []:
        ri = item.get("render_in")
        ro = item.get("render_out")
        if ri is None or ro is None:
            continue
        ri = float(ri)
        ro = float(ro)
        if ro <= ri:
            continue

        if prev_out is not None and prev_scene_id and ri > prev_out + 0.001:
            segments.append(
                TimelineVisualSegment(
                    kind="freeze_gap",
                    scene_id=prev_scene_id,
                    duration=round(ri - prev_out, 3),
                )
            )

        if item.get("type") == "scene":
            scene_id = str(item.get("scene_id") or "")
            if not scene_id:
                continue
            segments.append(
                TimelineVisualSegment(
                    kind="scene",
                    scene_id=scene_id,
                    duration=round(ro - ri, 3),
                )
            )
            prev_scene_id = scene_id
        elif item.get("type") == "beat_pause":
            scene_id = str(item.get("after_scene_id") or prev_scene_id or "")
            if not scene_id:
                continue
            segments.append(
                TimelineVisualSegment(
                    kind="beat_pause",
                    scene_id=scene_id,
                    duration=round(ro - ri, 3),
                )
            )
            prev_scene_id = scene_id

        prev_out = ro

    return segments


def _is_static_visual(visual_path: Path, visual_type: str) -> bool:
    return Path(visual_path).suffix.lower() in _STATIC_IMAGE_EXTS or visual_type == "Image"


def _build_timeline_render_jobs(
    segments: list[TimelineVisualSegment],
    scenes_by_id: dict[str, dict],
    visual_paths_by_scene: dict[str, Path],
) -> list[_TimelineRenderJob]:
    jobs: list[_TimelineRenderJob] = []
    for segment in segments:
        scene = scenes_by_id.get(segment.scene_id)
        visual_path = visual_paths_by_scene.get(segment.scene_id)
        if scene is None or visual_path is None:
            raise RuntimeError(f"{segment.scene_id}: visual not ready for timeline render")

        visual_type = str(scene.get("visual_type") or "Video")
        if (
            segment.kind != "scene"
            and jobs
            and jobs[-1].segment.scene_id == segment.scene_id
            and not jobs[-1].freeze_only
            and _is_static_visual(visual_path, visual_type)
        ):
            previous = jobs[-1]
            jobs[-1] = _TimelineRenderJob(
                segment=previous.segment,
                duration=round(previous.duration + segment.duration, 3),
                freeze_only=False,
            )
            continue

        jobs.append(
            _TimelineRenderJob(
                segment=segment,
                duration=segment.duration,
                freeze_only=segment.kind != "scene",
            )
        )
    return jobs


def build_visual_segment_command(
    visual_path: Path,
    visual_type: str,
    effect: str,
    duration: float,
    output_path: Path,
    width: int,
    height: int,
    fps: int = FPS,
    freeze_only: bool = False,
    source_duration: float | None = None,
) -> list[str]:
    """Build ffmpeg command for one visual-only segment."""
    visual_path = Path(visual_path)
    output_path = Path(output_path)
    is_static = visual_path.suffix.lower() in _STATIC_IMAGE_EXTS or visual_type == "Image"

    if freeze_only and not is_static:
        input_args = ["-sseof", "-0.1", "-i", str(visual_path)]
        source_is_video = True
        segment_visual_type = visual_type
        duration_design = 0.0
    elif is_static:
        input_args = ["-loop", "1", "-i", str(visual_path)]
        source_is_video = False
        segment_visual_type = "Image"
        duration_design = duration
    else:
        input_args = ["-i", str(visual_path)]
        source_is_video = True
        segment_visual_type = visual_type
        duration_design = source_duration or duration

    visual_filter = build_visual_filter_with_fit(
        visual_type=segment_visual_type,
        duration_design=duration_design,
        duration_adjusted=duration,
        effect="no_effect" if freeze_only else effect,
        width=width,
        height=height,
        fps=fps,
        source_is_video=source_is_video,
    )

    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *input_args,
        "-vf", visual_filter,
        "-t", f"{duration:.3f}",
        "-an",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(output_path),
    ]


def probe_media_duration(path: Path) -> float | None:
    """Return media duration in seconds via ffprobe, or None if unavailable."""
    result = run_tracked(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        return None
    try:
        duration = float((result.stdout or "").strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def render_visual_segment(
    visual_path: Path,
    visual_type: str,
    effect: str,
    duration: float,
    output_path: Path,
    width: int,
    height: int,
    fps: int = FPS,
    freeze_only: bool = False,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    visual_path = Path(visual_path)
    is_static = visual_path.suffix.lower() in _STATIC_IMAGE_EXTS or visual_type == "Image"
    source_duration = None if is_static or freeze_only else probe_media_duration(visual_path)
    cmd = build_visual_segment_command(
        visual_path=visual_path,
        visual_type=visual_type,
        effect=effect,
        duration=duration,
        output_path=output_path,
        width=width,
        height=height,
        fps=fps,
        freeze_only=freeze_only,
        source_duration=source_duration,
    )
    result = run_tracked(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg visual segment failed: {(result.stderr or '')[-1500:]}")
    return output_path


def render_timeline_visuals(
    timeline: dict,
    scenes_by_id: dict[str, dict],
    visual_paths_by_scene: dict[str, Path],
    output_path: Path,
    work_dir: Path,
    width: int,
    height: int,
    fps: int = FPS,
    progress_cb=None,
) -> Path:
    segments = build_timeline_visual_segments(timeline)
    if not segments:
        raise ValueError("Timeline has no renderable visual segments")
    jobs = _build_timeline_render_jobs(segments, scenes_by_id, visual_paths_by_scene)

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    total = len(jobs)
    for idx, job in enumerate(jobs, start=1):
        segment = job.segment
        scene = scenes_by_id.get(segment.scene_id)
        visual_path = visual_paths_by_scene.get(segment.scene_id)
        if scene is None or visual_path is None:
            raise RuntimeError(f"{segment.scene_id}: visual not ready for timeline render")
        out = work_dir / f"timeline-seg-{idx:04d}.mp4"
        render_visual_segment(
            visual_path=visual_path,
            visual_type=str(scene.get("visual_type") or "Video"),
            effect=str(scene.get("effect") or "no_effect"),
            duration=job.duration,
            output_path=out,
            width=width,
            height=height,
            fps=fps,
            freeze_only=job.freeze_only,
        )
        rendered.append(out)
        if progress_cb is not None:
            progress_cb(idx, total, segment)

    return assemble_concat(rendered, output_path)
