"""Build ffmpeg drawtext filter chain for subtitle phrases.

The chain is one drawtext per phrase, each gated by an `enable=between(t, ...)`
expression so only the active phrase shows. Phrases use the scene-relative
timestamps already computed by the caller.
"""

from __future__ import annotations

from pathlib import Path

from core.voice_mapping import SubtitlePhrase

DEFAULT_FONT_PATH = Path("C:/Windows/Fonts/arialbd.ttf")
LINGER_S = 0.30  # keep phrase visible briefly after its `end`


def _ffmpeg_path(p: Path) -> str:
    """Escape a Windows path for use inside an ffmpeg filter string."""
    return str(p).replace("\\", "/").replace(":", "\\:")


def _ffmpeg_text(text: str) -> str:
    """Escape user text inside drawtext text=''."""
    return (
        text.replace("\\", "\\\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )


def build_subtitle_drawtext_chain(
    phrases: list[SubtitlePhrase],
    canvas_w: int,
    canvas_h: int,
    font_path: Path | None = None,
) -> str:
    """Return a drawtext filter chain (no trailing comma).

    Empty string if there are no phrases. One drawtext per phrase; only the
    phrase whose [start, end+linger] window contains the current time is drawn.
    """
    if not phrases:
        return ""

    fp = Path(font_path) if font_path else DEFAULT_FONT_PATH
    if not fp.exists():
        # Soft-fail: drawtext without fontfile uses ffmpeg's default font.
        font_str = ""
    else:
        font_str = _ffmpeg_path(fp)

    y_pos = int(canvas_h * 0.80)
    font_size = 54 if canvas_w == 1080 else 60

    parts: list[str] = []
    for phrase in phrases:
        text = _ffmpeg_text(phrase.text)
        enable_expr = f"between(t,{phrase.start:.2f},{phrase.end + LINGER_S:.2f})"
        attrs = [
            f"text='{text}'",
            f"fontsize={font_size}",
            "fontcolor=yellow",
            "borderw=4",
            "bordercolor=black",
            "x=(w-text_w)/2",
            f"y={y_pos}",
            f"enable='{enable_expr}'",
        ]
        if font_str:
            attrs.insert(0, f"fontfile='{font_str}'")
        parts.append("drawtext=" + ":".join(attrs))

    return ",".join(parts)
