# Phase 4 — ASS Karaoke Subtitle Generation

> **Goal**: Generate single ASS file với karaoke effect cho final video.
> **Effort**: 2-3h
> **Dependency**: pysubs2 (NEW)

---

## Install pysubs2

Add vào `requirements.txt`:
```
pysubs2>=1.7.0
```

Install:
```bash
.venv\Scripts\activate
uv pip install pysubs2
```

Verify:
```python
python -c "import pysubs2; print(pysubs2.__version__)"
```

---

## Module: `voice/ass_generator.py` (NEW)

```python
"""
Generate single ASS file với karaoke effect.

Style: Arial Bold 50px, white base, yellow highlight, smooth fill (\\kf).
"""

import pysubs2
from pathlib import Path
from loguru import logger as log


# === Style configuration ===
ASS_FONT = "Arial"
ASS_FONTSIZE = 50
ASS_BOLD = True

# Colors (BGR for ASS, NOT RGB)
ASS_PRIMARY_COLOR = (255, 255, 255)    # white (after highlight passes)
ASS_SECONDARY_COLOR = (0, 255, 255)    # yellow (highlight) - BGR(0,255,255) = yellow
ASS_OUTLINE_COLOR = (0, 0, 0)          # black outline
ASS_OUTLINE = 2.0
ASS_SHADOW = 1.0

# Position
ASS_ALIGNMENT = pysubs2.Alignment.BOTTOM_CENTER  # 2
ASS_MARGIN_V = 100  # pixels from bottom (1080p video → ~80% from top)


def generate_final_ass(
    voice_mapping: dict,
    output_path: Path,
    video_width: int = 1920,
    video_height: int = 1080,
) -> Path:
    """
    Generate single ASS file with cumulative scene timing for the full final video.
    
    Args:
        voice_mapping: dict from voice_aligner output
        output_path: where to save final.ass
        video_width, video_height: must match final video resolution
    
    Returns:
        output_path
    """
    
    subs = pysubs2.SSAFile()
    subs.info["Title"] = "Story Video Subtitles"
    subs.info["PlayResX"] = str(video_width)
    subs.info["PlayResY"] = str(video_height)
    subs.info["WrapStyle"] = "0"
    subs.info["ScaledBorderAndShadow"] = "yes"
    
    # Build style
    style = pysubs2.SSAStyle()
    style.fontname = ASS_FONT
    style.fontsize = ASS_FONTSIZE
    style.bold = ASS_BOLD
    style.primarycolor = pysubs2.Color(*ASS_PRIMARY_COLOR)
    style.secondarycolor = pysubs2.Color(*ASS_SECONDARY_COLOR)
    style.outlinecolor = pysubs2.Color(*ASS_OUTLINE_COLOR)
    style.outline = ASS_OUTLINE
    style.shadow = ASS_SHADOW
    style.alignment = ASS_ALIGNMENT
    style.marginv = ASS_MARGIN_V
    
    subs.styles["Default"] = style
    
    # Build events with cumulative timing
    cursor_ms = 0  # cumulative position in final video (ms)
    
    for vs in voice_mapping["scenes"]:
        scene_dur_ms = int(vs["duration_adjusted"] * 1000)
        
        if vs.get("is_silent") or not vs.get("subtitle_phrases"):
            cursor_ms += scene_dur_ms
            continue
        
        scene_voice_in = vs["voice_in"]
        
        for phrase in vs["subtitle_phrases"]:
            # Phrase start/end relative to scene (subtract scene's voice_in)
            phrase_offset_in_scene_ms = int((phrase["start"] - scene_voice_in) * 1000)
            phrase_dur_ms = int((phrase["end"] - phrase["start"]) * 1000)
            
            # Absolute timing in final video
            abs_start_ms = cursor_ms + phrase_offset_in_scene_ms
            abs_end_ms = abs_start_ms + phrase_dur_ms
            
            # Build karaoke text với \kf tags
            karaoke_text = _build_karaoke_text(phrase["words"])
            
            event = pysubs2.SSAEvent(
                start=abs_start_ms,
                end=abs_end_ms,
                style="Default",
                text=karaoke_text,
            )
            subs.events.append(event)
        
        cursor_ms += scene_dur_ms
    
    # Sort events by start time (defensive)
    subs.events.sort(key=lambda e: e.start)
    
    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(output_path))
    
    log.info(
        f"Generated ASS: {output_path.name} "
        f"({len(subs.events)} subtitle events, total {cursor_ms / 1000:.2f}s)"
    )
    return output_path


def _build_karaoke_text(words: list[dict]) -> str:
    """
    Build karaoke text using \\kf tags.
    
    \\kf<centiseconds> = smooth fill highlight for next word.
    
    Example output:
        {\\kf30}Rain {\\kf25}taps {\\kf40}softly
    """
    parts = []
    for word in words:
        word_text = word["word"].strip()
        if not word_text:
            continue
        
        # Calculate duration in centiseconds (1cs = 10ms)
        duration_ms = (word["end"] - word["start"]) * 1000
        duration_cs = max(1, int(duration_ms / 10))  # min 1cs
        
        # Escape special chars in text (rare for English but safe)
        word_safe = word_text.replace("{", "\\{").replace("}", "\\}")
        
        parts.append(f"{{\\kf{duration_cs}}}{word_safe}")
    
    # Join with spaces (preserve spacing between words)
    return " ".join(parts)


def preview_ass(ass_path: Path, num_events: int = 5):
    """Print first N events for debugging."""
    subs = pysubs2.load(str(ass_path))
    log.info(f"ASS preview: {len(subs.events)} total events")
    for i, evt in enumerate(subs.events[:num_events]):
        log.info(
            f"  [{i}] {evt.start}ms - {evt.end}ms ({(evt.end - evt.start) / 1000:.2f}s): "
            f"{evt.text[:80]}..."
        )
```

---

## Test plan

### Test 1: Generate ASS from voice_mapping

```python
import json
from pathlib import Path
from voice.ass_generator import generate_final_ass, preview_ass

voice_mapping = json.loads(Path("test_run/voice_mapping.json").read_text())

ass_path = generate_final_ass(
    voice_mapping=voice_mapping,
    output_path=Path("test_run/final.ass"),
    video_width=1920,
    video_height=1080,
)

assert ass_path.exists()
preview_ass(ass_path, num_events=10)
```

Expected output:
```
[INFO] Generated ASS: final.ass (12 subtitle events, total 29.88s)
[INFO] ASS preview: 12 total events
[INFO]   [0] 0ms - 4100ms (4.10s): {\kf50}Rain {\kf40}taps {\kf50}softly...
[INFO]   [1] 4100ms - 8220ms (4.12s): {\kf45}on {\kf30}the...
...
```

### Test 2: Verify ASS file structure

Open `final.ass` in text editor:

```
[Script Info]
Title: Story Video Subtitles
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, ...
Style: Default,Arial,50,&H00FFFFFF,&H0000FFFF,&H00000000,...

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:04.10,Default,,0,0,0,,{\kf50}Rain {\kf40}taps {\kf50}softly...
...
```

### Test 3: Apply ASS to test video

```bash
# Generate ASS first
python -c "from voice.ass_generator import generate_final_ass; ..."

# Apply via ffmpeg
ffmpeg -y -i test_run/final_raw.mp4 \
  -vf "subtitles='test_run/final.ass'" \
  -c:v libx264 -c:a copy \
  test_run/test_with_subs.mp4
```

Verify visually:
- Subtitle hiện đúng position (~80% từ trên xuống)
- Word-by-word karaoke (yellow fill từ trái sang phải)
- Font Arial Bold size ~50px
- Outline đen rõ
- Center aligned

### Test 4: Silent scene handling

```python
# voice_mapping with mix silent + voiced scenes
voice_mapping = {
    "scenes": [
        {"id": "SCENE-01", "is_silent": False, "duration_adjusted": 5.0,
         "voice_in": 0, "voice_out": 5, "subtitle_phrases": [{"text": "Hello", "start": 0, "end": 1, "words": [{"word": "Hello", "start": 0, "end": 1}]}]},
        {"id": "SCENE-02", "is_silent": True, "duration_adjusted": 3.0,
         "voice_in": None, "voice_out": None, "subtitle_phrases": []},
        {"id": "SCENE-03", "is_silent": False, "duration_adjusted": 4.0,
         "voice_in": 5, "voice_out": 9, "subtitle_phrases": [{"text": "World", "start": 5, "end": 6, "words": [{"word": "World", "start": 5, "end": 6}]}]},
    ]
}

ass_path = generate_final_ass(voice_mapping, Path("/tmp/test.ass"))

# Verify:
# - SCENE-01 subtitle: 0ms - ~1000ms (relative to final start)
# - SCENE-02 silent: NO subtitles (3s gap)
# - SCENE-03 subtitle: starts at 8000ms (= 5000 SCENE-01 + 3000 SCENE-02)
```

### Test 5: Edge cases

```python
# Empty voice_mapping
voice_mapping = {"scenes": []}
ass_path = generate_final_ass(voice_mapping, Path("/tmp/empty.ass"))
# Should generate empty ASS without crash

# Phrase with words containing special chars
phrase = {
    "text": "Hello, {world}!",
    "start": 0, "end": 2,
    "words": [
        {"word": "Hello,", "start": 0, "end": 1},
        {"word": "{world}!", "start": 1, "end": 2},
    ]
}
# Verify {} are escaped properly in karaoke text
```

---

## Color reference (BGR for ASS)

ASS uses BGR not RGB. Common colors:

| Color | RGB | BGR (for pysubs2.Color) |
|---|---|---|
| White | (255,255,255) | (255,255,255) — symmetric |
| Yellow | (255,255,0) | (0,255,255) |
| Red | (255,0,0) | (0,0,255) |
| Green | (0,255,0) | (0,255,0) — symmetric |
| Blue | (0,0,255) | (255,0,0) |
| Black | (0,0,0) | (0,0,0) — symmetric |

→ pysubs2.Color(R, G, B) input là RGB internal, library tự convert.
→ Mình dùng `pysubs2.Color(255, 255, 255)` cho white, `pysubs2.Color(255, 255, 0)` cho yellow (RGB).

**Wait — verify pysubs2 Color signature**:

```python
# pysubs2 Color signature: Color(r, g, b, a=0)
# So pysubs2.Color(255, 255, 0) = yellow in RGB
```

→ Update code in module:
```python
ASS_PRIMARY_COLOR = (255, 255, 255)   # white RGB
ASS_SECONDARY_COLOR = (255, 255, 0)   # yellow RGB
ASS_OUTLINE_COLOR = (0, 0, 0)         # black RGB
```

→ pysubs2 sẽ tự convert sang BGR khi save ASS.

---

## Build order

1. Install pysubs2 (5 phút)
2. Create `voice/ass_generator.py` (1.5h)
3. Test 1 với voice_mapping hiện tại (15 phút)
4. Test 3 apply ASS visually (15 phút)
5. Tweak style nếu cần (font size, position) (15 phút)
6. Commit

**Total: ~2-3h**

---

## Confirm trước khi code

- [ ] pysubs2 install thành công
- [ ] FFmpeg có libass (verify với `ffmpeg -version | findstr libass`)
- [ ] voice_mapping.json từ Phase 3 đã có data đúng (subtitle_phrases với words)
- [ ] Có test video để apply ASS verify visual

→ Build xong test pass → Phase 5 (Render với extend/speedup + 2-pass).
