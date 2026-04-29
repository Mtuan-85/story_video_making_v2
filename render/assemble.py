"""Concat scene .mp4 files + (optional) BGM mix → final.mp4."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from loguru import logger as log

from render.bgm_mixer import build_bgm_filter, pick_bgm_files
from render.composite import get_duration


async def _run_ffmpeg(cmd: list[str], desc: str) -> tuple[int, str]:
    log.debug(f"{desc}: ffmpeg ... ({len(cmd)} args)")
    # subprocess.run + asyncio.to_thread — see composite.py rationale.
    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=False,
    )
    err = (result.stderr.decode("utf-8", errors="replace") or "").strip()[-1000:]
    return int(result.returncode or 0), err


async def assemble_final(
    scene_videos: list[Path],
    output_path: Path,
    bgm_dir: Path | None = None,
    canvas_w: int = 1920,
    canvas_h: int = 1080,
    fps: int = 30,
) -> dict:
    """Concat all scene videos, optionally overlay BGM under the voice track.

    Step 1: filter_complex concat into `concat.mp4` (audio + video joined).
    Step 2: if any BGM file present, mix with amix → `output_path`.
    """
    if not scene_videos:
        return {"ok": False, "error": "no scene videos to assemble"}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = output_path.parent / ".tmp_assemble"
    work_dir.mkdir(parents=True, exist_ok=True)
    concat_path = work_dir / "concat.mp4"

    # ---- Step 1: concat ------------------------------------------------------
    cmd: list[str] = ["ffmpeg", "-y"]
    for v in scene_videos:
        cmd += ["-i", str(v)]

    n = len(scene_videos)
    parts: list[str] = []
    for i in range(n):
        parts.append(
            f"[{i}:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,"
            f"crop={canvas_w}:{canvas_h},setsar=1,fps={fps}[v{i}]"
        )
        # Pad audio with anullsrc if input has no audio stream — else aresample.
        parts.append(f"[{i}:a]aresample=44100:async=1[a{i}]")

    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]")

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        str(concat_path),
    ]
    log.info(f"Assembling {n} scene videos → {concat_path.name}")
    rc, err = await _run_ffmpeg(cmd, "concat")
    if rc != 0:
        log.error(f"Concat failed: {err}")
        return {"ok": False, "error": f"concat_failed: {err[-300:]}"}

    # ---- Step 2: BGM (optional) ---------------------------------------------
    bgm_files = pick_bgm_files(bgm_dir)
    if not bgm_files:
        try:
            if output_path.exists():
                output_path.unlink()
            concat_path.replace(output_path)
        except OSError as e:
            return {"ok": False, "error": f"rename_failed: {e}"}
        return {"ok": True, "has_bgm": False, "path": str(output_path)}

    bgm_path = bgm_files[0]
    target_dur = get_duration(concat_path)
    if target_dur <= 0:
        return {"ok": False, "error": "ffprobe failed on concat output"}

    log.info(f"Adding BGM {bgm_path.name} (target {target_dur:.2f}s)")
    bgm_filter = build_bgm_filter(target_dur)
    cmd2 = [
        "ffmpeg", "-y",
        "-i", str(concat_path),
        "-i", str(bgm_path),
        "-filter_complex",
        f"[1:a]{bgm_filter}[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    rc2, err2 = await _run_ffmpeg(cmd2, "bgm_mix")
    if rc2 != 0:
        log.error(f"BGM mix failed: {err2}")
        return {"ok": False, "error": f"bgm_mix_failed: {err2[-300:]}"}

    try:
        concat_path.unlink(missing_ok=True)
    except OSError:
        pass

    return {"ok": True, "has_bgm": True, "path": str(output_path)}
