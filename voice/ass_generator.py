"""Generate single ASS file with karaoke effect for the final composite video.

Style: Arial Bold ~50px, white base, yellow highlight, smooth fill (\\kf).
Timing for each scene is cumulative based on `duration_adjusted`, so the ASS
matches the assembled output regardless of voice gaps trimmed away.
"""

from __future__ import annotations

from pathlib import Path

import pysubs2
from loguru import logger as log


# === Style configuration ===
ASS_FONT = "Arial"
ASS_FONTSIZE = 50
ASS_BOLD = True

# pysubs2.Color takes RGB (it converts to BGR &Hxxxxxx internally on save).
# `\kf` smooth karaoke fills text from SecondaryColour → PrimaryColour, so:
#   PrimaryColour   = the "sung" colour (after the fill arrives) → YELLOW
#   SecondaryColour = the "unsung" colour (before the fill)      → WHITE
ASS_PRIMARY_RGB = (255, 255, 0)      # yellow (sung, post-fill)
ASS_SECONDARY_RGB = (255, 255, 255)  # white (unsung, pre-fill)
ASS_OUTLINE_RGB = (0, 0, 0)          # black outline
ASS_OUTLINE = 2.0
ASS_SHADOW = 1.0

ASS_ALIGNMENT = pysubs2.Alignment.BOTTOM_CENTER  # 2
ASS_MARGIN_V = 100  # px from bottom


def generate_final_ass(
    voice_mapping: dict,
    output_path: Path,
    video_width: int = 1920,
    video_height: int = 1080,
) -> Path:
    """Write a single ASS file aligned to the cumulative composite timeline.

    Args:
        voice_mapping: dict from `align_voice_to_scenes`.
        output_path: target .ass path.
        video_width, video_height: must match the final video resolution so
            libass scales correctly.

    Returns:
        output_path
    """
    output_path = Path(output_path)

    subs = pysubs2.SSAFile()
    subs.info["Title"] = "Story Video Subtitles"
    subs.info["PlayResX"] = str(video_width)
    subs.info["PlayResY"] = str(video_height)
    subs.info["WrapStyle"] = "0"
    subs.info["ScaledBorderAndShadow"] = "yes"

    style = pysubs2.SSAStyle()
    style.fontname = ASS_FONT
    style.fontsize = ASS_FONTSIZE
    style.bold = ASS_BOLD
    style.primarycolor = pysubs2.Color(*ASS_PRIMARY_RGB)
    style.secondarycolor = pysubs2.Color(*ASS_SECONDARY_RGB)
    style.outlinecolor = pysubs2.Color(*ASS_OUTLINE_RGB)
    style.outline = ASS_OUTLINE
    style.shadow = ASS_SHADOW
    style.alignment = ASS_ALIGNMENT
    style.marginv = ASS_MARGIN_V
    subs.styles["Default"] = style

    cursor_ms = 0  # cumulative position in final video

    for vs in voice_mapping.get("scenes", []):
        # Render duration override: subtitle timing must match what is on screen.
        scene_dur_s = vs.get("render_duration") or vs.get("duration_adjusted", 0)
        scene_dur_ms = int(round(float(scene_dur_s) * 1000))

        if vs.get("is_silent") or not vs.get("subtitle_phrases"):
            cursor_ms += scene_dur_ms
            continue

        scene_voice_in = vs.get("voice_in")
        if scene_voice_in is None:
            cursor_ms += scene_dur_ms
            continue

        for phrase in vs["subtitle_phrases"]:
            phrase_offset_in_scene_ms = int(round((phrase["start"] - scene_voice_in) * 1000))
            phrase_dur_ms = int(round((phrase["end"] - phrase["start"]) * 1000))

            if phrase_dur_ms <= 0:
                continue

            abs_start_ms = cursor_ms + max(0, phrase_offset_in_scene_ms)
            abs_end_ms = abs_start_ms + phrase_dur_ms

            karaoke_text = _build_karaoke_text(phrase.get("words", []))
            if not karaoke_text:
                continue

            event = pysubs2.SSAEvent(
                start=abs_start_ms,
                end=abs_end_ms,
                style="Default",
                text=karaoke_text,
            )
            subs.events.append(event)

        cursor_ms += scene_dur_ms

    subs.events.sort(key=lambda e: e.start)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(output_path))

    log.info(
        f"Generated ASS: {output_path.name} "
        f"({len(subs.events)} subtitle events, total {cursor_ms / 1000:.2f}s)"
    )
    return output_path


def _build_karaoke_text(words: list[dict]) -> str:
    """Build karaoke text with \\kf<centiseconds> per word.

    \\kf = smooth left-to-right fill. 1cs = 10ms.
    """
    parts: list[str] = []
    for word in words:
        word_text = (word.get("word") or "").strip()
        if not word_text:
            continue

        duration_ms = (word["end"] - word["start"]) * 1000.0
        duration_cs = max(1, int(round(duration_ms / 10)))

        word_safe = word_text.replace("{", "\\{").replace("}", "\\}")

        parts.append(f"{{\\kf{duration_cs}}}{word_safe}")

    return " ".join(parts)


def preview_ass(ass_path: Path, num_events: int = 5) -> None:
    """Log first N events from an ASS file (debug helper)."""
    subs = pysubs2.load(str(ass_path))
    log.info(f"ASS preview: {len(subs.events)} total events")
    for i, evt in enumerate(subs.events[:num_events]):
        log.info(
            f"  [{i}] {evt.start}ms - {evt.end}ms "
            f"({(evt.end - evt.start) / 1000:.2f}s): {evt.text[:80]}..."
        )
