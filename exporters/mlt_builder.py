"""Build MLT XML (Kdenlive's native format) from registered assets + timeline.

Per Sprint 2 §13 the builder must:
  1. profile (resolution + fps + colorspace)
  2. producers (one per unique asset)
  3. playlists (V1 visuals, A1 master audio, optional V2/A2)
  4. clip entries inserted with frame-accurate in/out
  5. markers/guides for beats, scenes, pauses
  6. tractor combining tracks

This module is PURE XML: no I/O of assets, no ffmpeg. The AssetRegistry
already resolved every path; the timeline JSON already has render_in/out.
Everything here is `ElementTree.SubElement` calls.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from loguru import logger as log

from exporters.asset_registry import AssetEntry, AssetRegistry
from exporters.timecode import mlt_in_out, sec_to_frame


PROFILE_BY_ASPECT = {
    "16:9": {
        "description": "1920x1080 30fps",
        "width": "1920", "height": "1080",
        "display_aspect_num": "16", "display_aspect_den": "9",
        "sample_aspect_num": "1", "sample_aspect_den": "1",
        "progressive": "1",
        "frame_rate_num": "30", "frame_rate_den": "1",
        "colorspace": "709",
    },
    "9:16": {
        "description": "1080x1920 30fps",
        "width": "1080", "height": "1920",
        "display_aspect_num": "9", "display_aspect_den": "16",
        "sample_aspect_num": "1", "sample_aspect_den": "1",
        "progressive": "1",
        "frame_rate_num": "30", "frame_rate_den": "1",
        "colorspace": "709",
    },
}


# Marker colors (Kdenlive guide.color expects integer indexes)
GUIDE_COLOR_BEAT = "1"     # blue
GUIDE_COLOR_SCENE = "2"    # green
GUIDE_COLOR_PAUSE = "3"    # orange
GUIDE_COLOR_WARN = "4"     # red


def build_mlt_xml(
    timeline: dict,
    registry: AssetRegistry,
    aspect_ratio: str = "16:9",
    title: str = "Story Video",
) -> ET.Element:
    """Build the MLT root element. Caller writes via ElementTree.

    Args:
        timeline: parsed voice_matching_timeline.json
        registry: AssetRegistry with paths resolved + producer_ids
        aspect_ratio: "16:9" or "9:16"
        title: project title (header attribute)

    Returns:
        ET.Element <mlt> ready to be serialized.
    """
    fps = int(timeline.get("fps") or 30)
    profile = PROFILE_BY_ASPECT.get(aspect_ratio, PROFILE_BY_ASPECT["16:9"])
    total_duration_sec = float(timeline.get("total_duration") or 0)
    total_frames = sec_to_frame(total_duration_sec, fps)

    # ---- Root ----
    root = ET.Element("mlt", {
        "LC_NUMERIC": "C",
        "version": "7.16.0",
        "title": title,
        "producer": "main_bin",
    })

    # ---- Profile ----
    ET.SubElement(root, "profile", profile)

    # ---- Producers (one per unique asset in registry) ----
    _emit_producers(root, registry, total_frames=total_frames)

    # ---- V1 playlist: visual clips (scene + beat_pause) in timeline order ----
    plv = ET.SubElement(root, "playlist", id="playlist_v1")
    _emit_v1_entries(plv, timeline, registry, fps)

    # ---- A1 playlist: master audio as one continuous clip ----
    pla = ET.SubElement(root, "playlist", id="playlist_a1")
    master_entry = registry.get("audio:master")
    if master_entry:
        # Master audio length = total project duration
        ET.SubElement(pla, "entry", {
            "producer": master_entry.producer_id,
            "in": "0",
            "out": str(max(0, total_frames - 1)),
        })

    # ---- Tractor combines tracks ----
    tractor = ET.SubElement(root, "tractor", {
        "id": "main_tractor",
        "in": "0",
        "out": str(max(0, total_frames - 1)),
    })
    ET.SubElement(tractor, "track", producer="playlist_v1")
    if master_entry:
        ET.SubElement(tractor, "track", producer="playlist_a1")

    # ---- Markers / guides ----
    _emit_markers(tractor, timeline, fps)

    return root


def _emit_producers(
    root: ET.Element,
    registry: AssetRegistry,
    total_frames: int,
) -> None:
    """Emit one <producer> per unique AssetEntry."""
    for entry in registry.all_entries():
        # producer length: for master audio = total, for visuals = enough
        # frames to cover any reuse. We use total_frames as a safe upper
        # bound; individual playlist <entry> blocks set their own in/out.
        if entry.asset_type == "audio":
            length = max(1, total_frames)
        else:
            length = max(1, total_frames)

        prod = ET.SubElement(root, "producer", {
            "id": entry.producer_id,
            "in": "0",
            "out": str(max(0, length - 1)),
        })
        ET.SubElement(prod, "property", name="resource").text = _abs_url(entry.path)
        ET.SubElement(prod, "property", name="length").text = str(length)
        if entry.asset_type == "audio":
            ET.SubElement(prod, "property", name="vstream").text = "-1"
            ET.SubElement(prod, "property", name="astream").text = "0"
        ET.SubElement(prod, "property", name="mlt_service").text = "avformat-novalidate"
        # Kdenlive-friendly display name
        ET.SubElement(prod, "property", name="kdenlive:clipname").text = entry.display_name


def _emit_v1_entries(
    plv: ET.Element,
    timeline: dict,
    registry: AssetRegistry,
    fps: int,
) -> None:
    """Insert visual clips in timeline order onto V1.

    Spec §6.4: silent scene = normal V1 clip (no separate audio needed
    because master audio already has the gap).
    Spec §9: beat_pause is a SEPARATE V1 clip (image reused or freeze).
    """
    items = timeline.get("timeline") or []
    prev_render_out_frame = 0

    for it in items:
        itype = it.get("type")
        ri = it.get("render_in")
        ro = it.get("render_out")
        if itype not in ("scene", "beat_pause") or ri is None or ro is None:
            continue

        # Look up the clip key matching this item
        if itype == "scene":
            clip_key = f"scene:{it['scene_id']}"
        else:
            clip_key = f"pause:{it['beat_id']}"

        entry = registry.get(clip_key)
        if entry is None:
            # asset_registry decided this clip can't be placed
            continue

        mlt_in, mlt_out = mlt_in_out(ri, ro, fps)
        target_start_frame = sec_to_frame(ri, fps)

        # Insert blank if there's a gap (e.g. unmatched voiced scene before this)
        if target_start_frame > prev_render_out_frame:
            gap_frames = target_start_frame - prev_render_out_frame
            ET.SubElement(plv, "blank", length=str(gap_frames))

        ET.SubElement(plv, "entry", {
            "producer": entry.producer_id,
            "in": str(mlt_in),
            "out": str(mlt_out),
        })

        prev_render_out_frame = sec_to_frame(ro, fps)


def _emit_markers(tractor: ET.Element, timeline: dict, fps: int) -> None:
    """Add guides for beat starts, scene starts, beat pauses.

    Kdenlive reads guides from the tractor's `kdenlive:docproperties.guides`
    JSON property. We emit a JSON array string (Kdenlive 22+ format).
    """
    import json

    guides: list[dict] = []

    beats = timeline.get("beats") or []
    for b in beats:
        beat_id = b.get("beat_id") or ""
        role = b.get("beat_role") or ""
        emotion = b.get("emotion") or ""
        v_in = float(b.get("voice_in") or 0)
        v_out = float(b.get("voice_out") or 0)
        p_in = float(b.get("pause_in") or v_out)
        pause_sec = float(b.get("pause_after_sec") or 0)

        label_parts = [f"BEAT {beat_id}"]
        if role:
            label_parts.append(role)
        if emotion:
            label_parts.append(emotion)
        guides.append({
            "pos": _frame_to_kdenlive_pos(sec_to_frame(v_in, fps), fps),
            "comment": " — ".join(label_parts),
            "type": int(GUIDE_COLOR_BEAT),
        })
        guides.append({
            "pos": _frame_to_kdenlive_pos(sec_to_frame(v_out, fps), fps),
            "comment": f"BEAT-END {beat_id}",
            "type": int(GUIDE_COLOR_BEAT),
        })
        if pause_sec > 0:
            guides.append({
                "pos": _frame_to_kdenlive_pos(sec_to_frame(p_in, fps), fps),
                "comment": f"PAUSE {beat_id} — {pause_sec:.1f}s",
                "type": int(GUIDE_COLOR_PAUSE),
            })

    # Scene start markers (each timeline scene that's renderable)
    for it in timeline.get("timeline") or []:
        if it.get("type") != "scene":
            continue
        ri = it.get("render_in")
        if ri is None:
            continue
        guides.append({
            "pos": _frame_to_kdenlive_pos(sec_to_frame(ri, fps), fps),
            "comment": f"SCENE {it.get('scene_id') or '?'}",
            "type": int(GUIDE_COLOR_SCENE),
        })

    # Sort by pos
    guides.sort(key=lambda g: g["pos"])

    # Embed as Kdenlive doc property
    props = ET.SubElement(tractor, "property", name="kdenlive:docproperties.guides")
    props.text = json.dumps(guides, ensure_ascii=False)


def _frame_to_kdenlive_pos(frame: int, fps: int) -> str:
    """Kdenlive guide pos is HH:MM:SS.mmm string. Derived from frame at fps."""
    sec = frame / max(1, fps)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _abs_url(path: Path) -> str:
    """Forward-slash absolute path for MLT resource. Kdenlive opens both Windows
    backslashes and forward slashes but forward is the safer interchange."""
    return str(Path(path).resolve()).replace("\\", "/")


def write_mlt_xml(root: ET.Element, output_path: Path) -> Path:
    """Pretty-print + write .kdenlive file. Atomic via tmp + rename."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    tmp.replace(output_path)
    log.info(f"Wrote {output_path}")
    return output_path
