"""Export project to Kdenlive (MLT XML).

Kdenlive uses the MLT framework's XML serialisation as its native format
(`.kdenlive` files are MLT XML). We hand-build the XML directly because
no maintained `opentimelineio-kdenlive` adapter exists on PyPI; the structure
is small and stable.

Track layout written:
    V1 — visuals (one entry per scene, `duration_adjusted` from voice-first if present)
    A1 — voice (single concat producer covering V1 total duration)
    A2 — BGM (optional; first .mp3/.wav from `<project>/bgm/`)

Limitations (also documented in README):
    - Effects (zoom_in/out) NOT exported — user re-applies inside Kdenlive
    - Transitions NOT exported — user adds drag-drop
    - Subtitles exported separately as SRT next to the .kdenlive file
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from loguru import logger as log


PROFILE_BY_ASPECT = {
    "16:9": {
        "description": "1920x1080 30fps",
        "width": "1920",
        "height": "1080",
        "display_aspect_num": "16",
        "display_aspect_den": "9",
        "sample_aspect_num": "1",
        "sample_aspect_den": "1",
        "progressive": "1",
        "frame_rate_num": "30",
        "frame_rate_den": "1",
        "colorspace": "709",
    },
    "9:16": {
        "description": "1080x1920 30fps",
        "width": "1080",
        "height": "1920",
        "display_aspect_num": "9",
        "display_aspect_den": "16",
        "sample_aspect_num": "1",
        "sample_aspect_den": "1",
        "progressive": "1",
        "frame_rate_num": "30",
        "frame_rate_den": "1",
        "colorspace": "709",
    },
}
FPS = 30


def _seconds_to_frames(sec: float) -> int:
    return max(0, int(round(sec * FPS)))


def _abs_url(project_root: Path, rel_or_abs: str) -> str:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = (project_root / p).resolve()
    return str(p).replace("\\", "/")


def _scene_duration_sec(scene, voice_mapping: dict | None) -> float:
    """Pick voice-first `duration_adjusted` if present, else design duration."""
    if voice_mapping:
        for vf in voice_mapping.get("voice_files", []):
            for sa in vf.get("scenes", []):
                if sa.get("id") == scene.id:
                    adj = float(sa.get("duration_adjusted") or 0.0)
                    if adj > 0:
                        return adj
                    return float(sa.get("voice_out", 0)) - float(sa.get("voice_in", 0))
    return float(scene.duration)


def _visual_path(project, scene_id: str) -> Path | None:
    state = project.get_scene_state(scene_id)
    # Prefer video if ready (slideshow/grok video). Fall back to image.
    vid = state.get("video", {})
    if vid.get("status") == "ready" and vid.get("path"):
        full = Path(vid["path"])
        if not full.is_absolute():
            full = project.paths.root / full
        if full.exists():
            return full
    img = state.get("image", {})
    if img.get("status") == "ready" and img.get("path"):
        full = Path(img["path"])
        if not full.is_absolute():
            full = project.paths.root / full
        if full.exists():
            return full
    return None


def _voice_path(project, voice_mapping: dict | None) -> Path | None:
    if not voice_mapping:
        return None
    files = voice_mapping.get("voice_files", [])
    if not files:
        return None
    rel = files[0].get("file")
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = project.paths.root / p
    return p if p.exists() else None


def _first_bgm(project) -> Path | None:
    bgm_dir = project.paths.bgm_dir
    if not bgm_dir.exists():
        return None
    for ext in (".mp3", ".m4a", ".wav"):
        for f in sorted(bgm_dir.glob(f"*{ext}")):
            return f
    return None


def _producer(parent: ET.Element, pid: str, url: str, frames_in: int, frames_out: int,
              audio_only: bool = False) -> None:
    p = ET.SubElement(parent, "producer", {
        "id": pid,
        "in": "0",
        "out": str(max(0, frames_out - 1)),
    })
    ET.SubElement(p, "property", name="resource").text = url
    ET.SubElement(p, "property", name="length").text = str(frames_out)
    if audio_only:
        ET.SubElement(p, "property", name="vstream").text = "-1"
        ET.SubElement(p, "property", name="astream").text = "0"
    ET.SubElement(p, "property", name="mlt_service").text = "avformat-novalidate"


def build_kdenlive_xml(
    project,
    voice_mapping: dict | None,
    output_path: Path,
) -> Path:
    """Build MLT XML for Kdenlive. Returns the written .kdenlive path."""
    aspect = project.scenes_json.meta.aspect_ratio
    profile = PROFILE_BY_ASPECT.get(aspect, PROFILE_BY_ASPECT["16:9"])

    # Per-scene durations + visual paths.
    scene_clips: list[tuple[str, Path, int]] = []  # (scene_id, path, frames)
    cumulative_frames = 0
    for scene in project.scenes:
        path = _visual_path(project, scene.id)
        if path is None:
            log.warning(f"[kdenlive] {scene.id}: no visual ready, skip")
            continue
        dur_sec = _scene_duration_sec(scene, voice_mapping)
        frames = _seconds_to_frames(dur_sec)
        if frames <= 0:
            continue
        scene_clips.append((scene.id, path, frames))
        cumulative_frames += frames
    if not scene_clips:
        raise RuntimeError("Không có scene nào có visual ready để export")

    # Root MLT element.
    root = ET.Element("mlt", {
        "LC_NUMERIC": "C",
        "version": "7.16.0",
        "title": project.scenes_json.meta.title or "Story Video",
        "producer": "main_bin",
    })

    # Profile.
    ET.SubElement(root, "profile", profile)

    # Visual producers (one per scene).
    for i, (sid, path, frames) in enumerate(scene_clips):
        _producer(root, pid=f"v_{i}", url=_abs_url(project.paths.root, str(path)),
                  frames_in=0, frames_out=frames)

    # Voice + BGM producers.
    voice_path = _voice_path(project, voice_mapping)
    if voice_path is not None:
        _producer(root, pid="audio_voice",
                  url=_abs_url(project.paths.root, str(voice_path)),
                  frames_in=0, frames_out=cumulative_frames, audio_only=True)
    bgm_path = _first_bgm(project)
    if bgm_path is not None:
        _producer(root, pid="audio_bgm",
                  url=_abs_url(project.paths.root, str(bgm_path)),
                  frames_in=0, frames_out=cumulative_frames, audio_only=True)

    # V1 playlist — sequential scenes.
    plv = ET.SubElement(root, "playlist", id="playlist_v1")
    for i, (sid, _path, frames) in enumerate(scene_clips):
        ET.SubElement(plv, "entry", {
            "producer": f"v_{i}",
            "in": "0",
            "out": str(max(0, frames - 1)),
        })

    # A1 playlist — voice.
    if voice_path is not None:
        pla = ET.SubElement(root, "playlist", id="playlist_a1")
        ET.SubElement(pla, "entry", {
            "producer": "audio_voice",
            "in": "0",
            "out": str(max(0, cumulative_frames - 1)),
        })

    # A2 playlist — BGM.
    if bgm_path is not None:
        plb = ET.SubElement(root, "playlist", id="playlist_a2")
        ET.SubElement(plb, "entry", {
            "producer": "audio_bgm",
            "in": "0",
            "out": str(max(0, cumulative_frames - 1)),
        })
        # Lower BGM volume relative to voice.
        ET.SubElement(plb, "property", name="kdenlive:audio_track").text = "1"

    # Tractor combines tracks.
    tractor = ET.SubElement(root, "tractor", {
        "id": "main_tractor",
        "in": "0",
        "out": str(max(0, cumulative_frames - 1)),
    })
    ET.SubElement(tractor, "track", producer="playlist_v1")
    if voice_path is not None:
        ET.SubElement(tractor, "track", producer="playlist_a1")
    if bgm_path is not None:
        ET.SubElement(tractor, "track", producer="playlist_a2")

    # Pretty-print + write.
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    log.info(
        f"Exported Kdenlive: {output_path} "
        f"({len(scene_clips)} clips, {cumulative_frames} frames @ {FPS}fps)"
    )
    return output_path


# --- SRT export ------------------------------------------------------------


def _seconds_to_srt(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def export_srt(voice_mapping: dict, output_path: Path) -> Path:
    """Build .srt from voice_mapping subtitle phrases (absolute timestamps)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    counter = 1
    for vf in voice_mapping.get("voice_files", []):
        for scene in vf.get("scenes", []):
            for ph in scene.get("subtitle_phrases", []):
                start = _seconds_to_srt(float(ph.get("start", 0)))
                end = _seconds_to_srt(float(ph.get("end", 0)))
                text = (ph.get("text") or "").strip()
                if not text:
                    continue
                lines.append(str(counter))
                lines.append(f"{start} --> {end}")
                lines.append(text)
                lines.append("")
                counter += 1
    output_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Exported SRT: {output_path} ({counter - 1} entries)")
    return output_path


def export_kdenlive(
    project,
    voice_mapping: dict | None,
    output_path: Path,
    also_srt: bool = True,
) -> tuple[Path, Path | None]:
    """Public entry: write .kdenlive + optional .srt next to it."""
    kdenlive_path = build_kdenlive_xml(project, voice_mapping, output_path)
    srt_path: Path | None = None
    if also_srt and voice_mapping:
        srt_path = kdenlive_path.with_suffix(".srt")
        export_srt(voice_mapping, srt_path)
    return kdenlive_path, srt_path
