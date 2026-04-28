# MIGRATION PLAN — Story Video Maker

> **Purpose**: Hướng dẫn Claude Code build các module còn thiếu cho project
> `D:\Projects\story_video_making`, học pattern từ project tham khảo
> `D:\Projects\gen_video_grok` (Parenting Tips - production code).
>
> **Status**: Foundation đã build (core/, voice/fish_tts.py, slideshow_v4/).
> **Next**: Build engines/grok/, render/, ui/, workers/ + cập nhật schema.

---

## 0. Trước khi bắt đầu — bro phải làm

### 0.1. Giải nén project tham khảo

Bro đã có file `gen_video_grok.rar`. Giải nén ra:

```
D:\Projects\gen_video_grok\           ← KHÔNG động vào, chỉ READ-ONLY
├── CLAUDE.md
├── story_render.py                   ← reference: composite + assemble + subtitle
├── grok-story-factory/
│   ├── grok-cdp-pipeline.py          ← reference: Grok Playwright actions
│   ├── pipeline_state.py             ← reference: state writer
│   └── estimator.py                  ← reference: time estimator
└── projects/                         ← reference: scenes.json examples
```

→ Đây là **NGUỒN ĐỌC**, không phải nguồn code chạy. Claude Code đọc các file
này để hiểu pattern, sau đó **viết code mới** trong `D:\Projects\story_video_making`.

### 0.2. Verify foundation đã có

Trong `D:\Projects\story_video_making\`, đảm bảo có:

```
story_video_making/
├── .venv/                  ← uv venv
├── core/                   ← Claude Code đã build (schema + project)
├── slideshow_v4/           ← copy nguyên (chroma + 6 animations)
├── voice/
│   └── fish_tts.py         ← TTS tool standalone (đã có)
├── examples/
│   └── scenes_voice_test.json
├── pyproject.toml
└── SPEC.md
```

Nếu thiếu file nào, dừng và báo trước khi tiếp tục.

### 0.3. Schema scenes.json đã bị thay đổi

**Quan trọng**: schema mới đã **bỏ** các field sau (so với SPEC.md cũ):
- `voice_batch_id` — đã chuyển sang file `voice_mapping.json` riêng
- `emotion` — user gen voice ngoài app, không dùng emotion field nữa

Schema mới ở mục 2 file này.

---

## 1. Build order (12 modules)

Build theo thứ tự này. Sau mỗi module, test rồi sang module kế tiếp.

| # | Module | File | Priority | Phụ thuộc |
|---|---|---|---|---|
| 1 | Schema update | `core/schema.py` | CRITICAL | - |
| 2 | Voice mapping | `core/voice_mapping.py` | HIGH | 1 |
| 3 | Engine Protocols | `engines/base.py` | HIGH | 1 |
| 4 | Grok selectors | `engines/grok/selectors.py` | HIGH | 3 |
| 5 | Grok actions | `engines/grok/actions.py` | HIGH | 4 |
| 6 | Grok engine | `engines/grok/engine.py` | HIGH | 5 |
| 7 | Render: Ken Burns | `render/ken_burns.py` | MEDIUM | - |
| 8 | Render: Composite + Assemble | `render/composite.py`, `render/assemble.py` | MEDIUM | - |
| 9 | Voice splitter | `voice/voice_split.py` | MEDIUM | 2 |
| 10 | Subtitle (segment-level) | `render/subtitle.py` | MEDIUM | 9 |
| 11 | UI + Workers | `ui/`, `workers/` | LOW | 1-10 |
| 12 | Estimator + State | `runtime/estimator.py`, `runtime/state_writer.py` | LOW | - |

---

## 2. Schema update — `core/schema.py`

### 2.1. Schema scenes.json (mới, đã bỏ field)

```python
from pydantic import BaseModel, Field
from typing import Literal


class Meta(BaseModel):
    project_id: str
    title: str
    aspect_ratio: Literal["16:9", "9:16"]
    language: Literal["vi", "en"]


class Settings(BaseModel):
    baseStyle: str
    baseNegative: str
    topic: str
    image_quality: Literal["speed", "quality"] = "quality"
    video_resolution: Literal["480p", "720p"] = "720p"
    video_duration: Literal["6s", "10s"] = "10s"


VisualType = Literal[
    "image_grok",
    "video_grok",
    "slideshow_v4",
    "ken_burns_self",
    "ken_burns_cont",
]


class Scene(BaseModel):
    id: str
    visual_type: VisualType
    story_vi: str | None = None
    story_en: str | None = None
    imagePrompt: str
    videoPrompt: str | None = None
    duration: int = Field(ge=1, le=60)

    def get_story(self, lang: str) -> str:
        if lang == "vi":
            return self.story_vi or self.story_en or ""
        return self.story_en or self.story_vi or ""


class ScenesJson(BaseModel):
    version: Literal["1.0"]
    meta: Meta
    settings: Settings
    scenes: list[Scene]
```

### 2.2. Schema voice_mapping.json (file mới)

```python
class VoiceFileMapping(BaseModel):
    file: str  # path tương đối tới project root, vd: "voice/voice_01.mp3"
    scenes: list[str]  # ["SCENE-01", "SCENE-02", "SCENE-03"]


class VoiceMapping(BaseModel):
    version: Literal["1.0"]
    voice_files: list[VoiceFileMapping]

    def get_file_for_scene(self, scene_id: str) -> str | None:
        """Trả về path file mp3 chứa voice cho scene_id."""
        for vf in self.voice_files:
            if scene_id in vf.scenes:
                return vf.file
        return None

    def get_scene_index_in_file(self, scene_id: str) -> int | None:
        """Trả về thứ tự scene trong file (0-indexed)."""
        for vf in self.voice_files:
            if scene_id in vf.scenes:
                return vf.scenes.index(scene_id)
        return None
```

### 2.3. Update `core/project.py`

Project class load CẢ `scenes.json` VÀ `voice_mapping.json`:

```python
class Project:
    def __init__(self, project_dir: Path):
        self.dir = project_dir
        self.scenes_data = self._load_scenes()       # ScenesJson
        self.voice_mapping = self._load_voice_mapping()  # VoiceMapping | None
        self.state = self._load_or_init_state()      # ProjectState

    def _load_voice_mapping(self) -> VoiceMapping | None:
        path = self.dir / "voice_mapping.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return VoiceMapping(**json.load(f))
```

### 2.4. Test exit criteria

```python
# Test
from core.schema import ScenesJson, VoiceMapping
import json

scenes = ScenesJson(**json.load(open("examples/scenes_voice_test.json")))
print(f"Loaded {len(scenes.scenes)} scenes")

# voice_mapping.json optional, có thì load, không có thì None
```

---

## 3. Engine Protocols — `engines/base.py`

```python
from typing import Protocol
from pathlib import Path


class ImageEngine(Protocol):
    async def gen_image(
        self,
        prompt: str,
        settings: dict,
        ref_image: Path | None = None,
    ) -> Path:
        """Trả về path file ảnh đã download."""
        ...

    async def pick_best(
        self,
        candidates: list[Path],
        prompt: str,
        topic: str,
        style: str,
    ) -> int:
        """Trả về index ảnh best (Claude vision-based)."""
        ...


class VideoEngine(Protocol):
    async def gen_video(
        self,
        prompt: str,
        ref_image: Path,
        settings: dict,
    ) -> Path:
        """Image-to-Video. Trả về path mp4."""
        ...


class EngineConnection(Protocol):
    async def connect(self, cdp_url: str) -> None:
        ...

    async def disconnect(self) -> None:
        ...

    async def is_connected(self) -> bool:
        ...
```

---

## 4-6. Grok Engine

### 4. `engines/grok/selectors.py`

**REFERENCE**: Đọc `D:\Projects\gen_video_grok\grok-story-factory\grok-cdp-pipeline.py`
+ `D:\Projects\story_video_making\MASTER_grok_automation.md` (file SPEC trước)

Centralize tất cả selectors. Quan trọng: support cả **VN UI** và **EN UI** vì
Grok có thể hiển thị 2 language tùy account:

```python
# Mode switch
MODE_RADIO_GROUP = '[role="radio"]'
MODE_LABELS_VN = {"image": ["hình ảnh", "image"], "video": ["video"]}
MODE_LABELS_EN = {"image": ["image"], "video": ["video"]}

# Aspect ratio - dual selector (VN + EN)
ASPECT_BUTTON_VN = 'button[aria-label*="Tỷ lệ"]'
ASPECT_BUTTON_EN = 'button[aria-label^="Aspect Ratio"]'

# Quality / Resolution
QUALITY_LABELS = {
    "quality": ["Chất lượng", "Quality"],
    "speed": ["Tốc độ", "Speed"],
}

# Prompt input
PROMPT_INPUT = "div.ProseMirror[contenteditable='true']"
PROMPT_INPUT_FALLBACK = '[contenteditable="true"]'

# Submit
SUBMIT_BUTTON = 'button[aria-label^="Submit"]'

# Upload
UPLOAD_BUTTON = 'button[aria-label^="Upload"]'
FILE_INPUT = 'input[type="file"]'
FILE_INPUT_FALLBACK = 'input[name="files"]'

# Result
DOWNLOAD_BUTTON = 'button[aria-label^="Download"]'
BACK_BUTTON = 'div[aria-label^="Back"]'
VIDEO_ELEMENT = '#sd-video'

# Masonry (gen image)
MASONRY_SECTION = '[id^="imagine-masonry-section-"]'
MASONRY_SECTION_FIRST = '#imagine-masonry-section-0'

# Rate limit detection - dual fallback
RATE_LIMIT_TOAST = '[data-sonner-toast]'
RATE_LIMIT_ALERT = '[role="alert"]'
RATE_LIMIT_PHRASES = [
    "rate limit", "too many", "try again", "limit reached",
    "quá nhiều", "giới hạn", "thử lại",
]

# CRITICAL: download image filter
# Phân biệt placeholder noise vs real image bằng độ dài base64 data URI
MIN_DATA_URI_LEN = 250000  # ~180KB base64
```

### 5. `engines/grok/actions.py`

**REFERENCE**: Copy logic từ `grok-cdp-pipeline.py` các function:
- `navigate_to_imagine()` (dòng 122-134)
- `switch_mode()` (dòng 137-171) — có retry 3 lần
- `select_aspect_ratio()` (dòng 187-201)
- `type_prompt()` (dòng 204-258) — clear + type với verify
- `upload_image()` (dòng 272-278)
- `check_rate_limit()` (dòng 281-302)
- `handle_rate_limit_if_present()` (dòng 305-323)
- `download_image()` (dòng 365-433) — **CRITICAL**: filter placeholder by `MIN_DATA_URI_LEN`
- `download_video()` (dòng 436-472) — handle blob: vs http: src

**Refactor thành class**:

```python
class GrokActions:
    def __init__(self, page):
        self.page = page

    async def navigate_to_imagine(self): ...
    async def switch_mode(self, mode: str): ...
    async def set_quality(self, quality: str): ...
    async def set_aspect_ratio(self, ratio: str): ...
    async def set_video_resolution(self, res: str): ...
    async def set_video_duration(self, dur: str): ...
    async def type_prompt(self, text: str): ...
    async def upload_image(self, image_path: Path): ...
    async def submit(self): ...
    async def wait_image_ready(self, timeout=90000) -> dict: ...
    async def wait_video_ready(self, timeout=300000) -> dict: ...
    async def download_image(self, save_path: Path) -> tuple[int, int, int]: ...
    async def download_video(self, save_path: Path) -> int: ...
    async def click_back(self): ...
    async def detect_rate_limit(self) -> tuple[bool, str]: ...
    async def screenshot_debug(self, name: str): ...
```

### 6. `engines/grok/engine.py`

Implement `ImageEngine` + `VideoEngine` Protocol.

```python
class GrokEngine:
    def __init__(self, page):
        self.actions = GrokActions(page)

    async def gen_image(self, prompt, settings, ref_image=None) -> Path:
        """
        Implement ImageEngine protocol.
        Flow:
        1. navigate_to_imagine()
        2. switch_mode("image")
        3. set_quality(settings["image_quality"])
        4. set_aspect_ratio(settings["aspect_ratio"])
        5. if ref_image: upload_image(ref_image)
        6. type_prompt(prompt)
        7. submit()
        8. wait_image_ready()
        9. download_image(save_path)
        """
        ...

    async def gen_video(self, prompt, ref_image, settings) -> Path:
        """
        Implement VideoEngine protocol.
        Flow:
        1. navigate_to_imagine()
        2. switch_mode("video")
        3. set_video_resolution + duration + aspect_ratio
        4. upload_image(ref_image)
        5. type_prompt(prompt)
        6. submit()
        7. wait_video_ready()
        8. download_video(save_path)
        """
        ...

    async def pick_best(self, candidates, prompt, topic, style) -> int:
        """
        Subprocess Claude Code CLI vision pick.
        Reuse pattern từ slideshow_v4/claude_runner.py.
        Truyền context: project topic + style (mục mở rộng so với mode auto).
        """
        ...
```

### 6.4. Test exit criteria

```bash
# Sau khi build xong engines/grok/, test:
python -c "
from engines.grok.engine import GrokEngine
import asyncio

async def test():
    # Mock page (cần Brave debug port chạy)
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp('http://localhost:9222')
    page = browser.contexts[0].pages[0]

    engine = GrokEngine(page)
    img = await engine.gen_image(
        prompt='Simple flat 2D illustration of a kitchen',
        settings={'image_quality': 'quality', 'aspect_ratio': '16:9'}
    )
    print(f'Generated: {img}')

asyncio.run(test())
"
```

---

## 7. Ken Burns — `render/ken_burns.py`

**REFERENCE**: Đọc `D:\Projects\gen_video_grok\story_render.py` function
`find_best_frame()` (dòng 424-482) — pattern extract frame + scoring.

```python
"""
Ken Burns module - 2 modes:
- ken_burns_self: zoom-pan ảnh chính của scene đó
- ken_burns_cont: lấy frame cuối video scene N-1, zoom-pan

Output: video mp4 với Ken Burns animation.
"""

async def ken_burns_self(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str,  # "16:9" or "9:16"
    zoom_rate: float = 0.04,  # 4% per second
) -> Path:
    """
    ffmpeg zoompan filter trên ảnh tĩnh.

    Canvas size:
        16:9 → 1920x1080
        9:16 → 1080x1920

    Filter:
        zoompan=z='min(zoom+0.0008,1.5)':d={frames}:s={W}x{H}:fps=30
    """
    canvas = {"16:9": (1920, 1080), "9:16": (1080, 1920)}[aspect_ratio]
    fps = 30
    frames = int(duration_sec * fps)
    # ... build ffmpeg cmd
    ...


async def ken_burns_continuation(
    prev_video_path: Path,
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str,
    zoom_rate: float = 0.04,
) -> Path:
    """
    1. Extract last frame của prev_video → temp/last_frame.jpg
       ffmpeg -sseof -0.1 -i {prev_video} -vsync 0 -update 1 last_frame.jpg
    2. Apply ken_burns_self trên frame đó
    """
    ...
```

---

## 8. Composite + Assemble

### 8.1. `render/composite.py`

**REFERENCE**: Copy 95% từ `D:\Projects\gen_video_grok\story_render.py`
function `composite_scene()` (dòng 548-628).

Adjustments:
- Hard-code `aspect_ratio` "9:16" → param `aspect_ratio` configurable
- Thêm logic **speed-match** cho video clip (setpts trong [0.7, 1.4])
- Thêm warning return khi mismatch out-of-range

```python
async def composite_scene(
    visual_path: Path,           # ảnh hoặc video
    visual_type: str,            # để biết tĩnh hay động
    voice_path: Path | None,
    subtitle_frames_dir: Path | None,
    duration_sec: float,         # = voice duration nếu có voice, else scene.duration
    aspect_ratio: str,
    output_path: Path,
) -> dict:
    """
    Compose 1 scene = visual + subtitle + audio → mp4.

    Returns:
        {"ok": True, "warnings": [...], "duration_actual": ...}
        Warnings có thể có:
        - "speed_stretch_high" — clip-voice ratio out [0.7, 1.4]
    """
    # Get durations
    audio_dur = get_duration(voice_path) if voice_path else 0
    target_dur = audio_dur if audio_dur > 0 else duration_sec

    if visual is video:
        clip_dur = get_duration(visual_path)
        ratio = clip_dur / target_dur
        if 0.7 <= ratio <= 1.4:
            # OK, setpts stretch
            setpts_factor = ratio
        elif ratio > 1.4:
            # Trim clip
            ...
        elif ratio < 0.7:
            # Freeze tail
            ...
            warnings.append("speed_stretch_high")

    elif visual is image:
        # Ken Burns flexible duration
        ...

    # ffmpeg composite ...
    ...
```

### 8.2. `render/assemble.py`

**REFERENCE**: Copy 100% từ `story_render.py` function `assemble_final()`
(dòng 776-849). Hard-cut concat, KHÔNG dùng xfade (gây freeze VLC).

```python
async def assemble_scenes(
    scene_videos: list[Path],
    output_path: Path,
    aspect_ratio: str,
    fps: int = 30,
) -> Path:
    """
    Concat tất cả scene videos thành 1 final.mp4.

    Pre-process: normalize fps/resolution/sar/audio sample rate.
    Concat: dùng filter_complex concat filter (không dùng -f concat
    để tránh codec mismatch).

    Output: re-encode H.264 + AAC.
    """
    ...
```

---

## 9. Voice Splitter — `voice/voice_split.py`

**Mục tiêu**: User đặt file mp3 vào folder + khai báo `voice_mapping.json`.
App đọc mapping → cắt mỗi file mp3 thành scene_*.mp3 bằng silence detection.

```python
"""
voice_split.py - Cắt voice batch mp3 thành scene-level mp3.

Input:
    - voice_mapping.json đã user khai báo
    - Các file mp3 user nạp

Output:
    - voice/scene_<id>.mp3 cho mỗi scene
    - Update state.json voice.status = "ready"

Algorithm:
    For each voice_file in voice_mapping:
        1. Load file mp3
        2. ffmpeg silencedetect → list of silence intervals
        3. Map silence boundaries với scenes trong file
        4. Cut mỗi segment → scene_<id>.mp3
        5. Edge cases:
           - File chỉ có 1 scene → copy nguyên
           - Boundaries không khớp count → emit warning, fallback equal split
"""

import re
import subprocess
from pathlib import Path


def detect_silences(
    audio_path: Path,
    threshold_db: int = -30,
    min_duration: float = 0.3,
) -> list[dict]:
    """
    Run ffmpeg silencedetect.

    Returns: [{"start": 2.45, "end": 2.78}, ...]
    """
    cmd = [
        "ffmpeg", "-i", str(audio_path),
        "-af", f"silencedetect=n={threshold_db}dB:d={min_duration}",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr

    silences = []
    starts = re.findall(r"silence_start: ([\d.]+)", stderr)
    ends = re.findall(r"silence_end: ([\d.]+)", stderr)
    for s, e in zip(starts, ends):
        silences.append({"start": float(s), "end": float(e)})
    return silences


def find_boundaries(
    silences: list[dict],
    expected_count: int,
) -> list[float]:
    """
    Từ list silences → tìm N-1 boundary timestamps cho expected_count scenes.

    Strategy: pick top-(N-1) silences dài nhất.
    """
    needed = expected_count - 1
    if len(silences) < needed:
        return []  # không đủ silence để cắt

    # Sort by duration descending
    silences_sorted = sorted(
        silences,
        key=lambda s: s["end"] - s["start"],
        reverse=True,
    )
    top_n = sorted(silences_sorted[:needed], key=lambda s: s["start"])
    boundaries = [(s["start"] + s["end"]) / 2 for s in top_n]
    return boundaries


def split_audio_file(
    audio_path: Path,
    scene_ids: list[str],
    output_dir: Path,
) -> dict:
    """
    Cắt 1 file mp3 thành N scene_*.mp3.

    Returns: {
        "ok": bool,
        "scene_files": {"SCENE-01": Path, ...},
        "warnings": [...],
    }
    """
    n = len(scene_ids)

    # Edge case: 1 scene → copy nguyên
    if n == 1:
        out = output_dir / f"scene_{scene_ids[0]}.mp3"
        out.write_bytes(audio_path.read_bytes())
        return {"ok": True, "scene_files": {scene_ids[0]: out}, "warnings": []}

    # Detect silences + find boundaries
    total_dur = get_duration(audio_path)
    silences = detect_silences(audio_path)
    boundaries = find_boundaries(silences, n)

    warnings = []
    if len(boundaries) != n - 1:
        # Fallback: equal split
        warnings.append("voice_split_fallback_equal")
        boundaries = [(i + 1) * total_dur / n for i in range(n - 1)]

    # Cut bằng ffmpeg
    scene_files = {}
    starts = [0] + boundaries
    ends = boundaries + [total_dur]
    for i, sid in enumerate(scene_ids):
        out = output_dir / f"scene_{sid}.mp3"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-ss", str(starts[i]),
            "-to", str(ends[i]),
            "-c", "copy",
            str(out),
        ]
        subprocess.run(cmd, capture_output=True)
        scene_files[sid] = out

    return {"ok": True, "scene_files": scene_files, "warnings": warnings}


def split_all(
    project: Project,
) -> dict:
    """
    Đọc voice_mapping → split mỗi file → save scene_*.mp3 +
    update state.json voice status.
    """
    if not project.voice_mapping:
        raise ValueError("voice_mapping.json không tồn tại")

    output_dir = project.dir / "voice"
    results = {}
    for vf in project.voice_mapping.voice_files:
        audio_path = project.dir / vf.file
        result = split_audio_file(audio_path, vf.scenes, output_dir)
        for sid, path in result["scene_files"].items():
            duration = get_duration(path)
            project.update_scene_state(sid, "voice", {
                "status": "ready",
                "path": str(path),
                "duration_sec": duration,
            })
            for w in result["warnings"]:
                project.add_warning(sid, w)
            results[sid] = result

    return results
```

---

## 10. Subtitle (Segment-Level Karaoke) — `render/subtitle.py`

**Decision**: Phase 1 dùng **segment-level karaoke** (Cách B) — KHÔNG cần
Whisper-timestamped. Phrase-level highlight thay vì word-level.

**REFERENCE**: Đọc `D:\Projects\gen_video_grok\story_render.py` function
`render_subtitle_frames()` (dòng 275-419) — copy logic Pillow render, ADJUST
phần timing source từ word-level → phrase-level.

```python
"""
subtitle.py - Render karaoke subtitle PNG sequence.

Phase 1: Segment-level karaoke
- Split story text → phrases (max 5 từ, break tại dấu câu)
- Pair phrases → 2 lines/screen
- Mỗi phrase highlight VÀNG khi đọc, các phrase còn lại trắng
- KHÔNG cần word-level timestamps (không cần Whisper)
- Timing: dùng segment timestamps từ Fish ASR HOẶC heuristic split
  audio duration đều theo phrases

Phase 2 (future): word-level karaoke với Whisper-timestamped.
"""

from PIL import Image, ImageDraw, ImageFont
import re
import shutil
from pathlib import Path


# Style spec (copy từ Parenting Tips)
SUB_FONT_SIZE = 44
SUB_PHRASE_SIZE = 5  # max 5 từ/dòng
SUB_POSITION_Y = 0.85  # 85% từ top
COLOR_UNREAD = (255, 255, 255, 230)
COLOR_READ = (255, 215, 0, 255)  # #FFD700
COLOR_SHADOW = (0, 0, 0, 180)
LINE_GAP = 14


def split_text_to_phrases(text: str, max_words: int = 5) -> list[str]:
    """
    Heuristic split text → phrases.

    Rules:
    - Break tại dấu câu (. , ! ? ;)
    - Mỗi phrase max N từ
    - Trim whitespace
    """
    # Split tại dấu câu
    parts = re.split(r"(?<=[.!?,;])\s+", text)
    phrases = []
    for part in parts:
        words = part.split()
        # Nếu phrase quá dài, split thêm tại max_words
        for i in range(0, len(words), max_words):
            chunk = " ".join(words[i:i + max_words])
            if chunk:
                phrases.append(chunk)
    return phrases


def estimate_phrase_timings(
    phrases: list[str],
    total_duration: float,
) -> list[dict]:
    """
    Estimate start/end của mỗi phrase, weighted theo số từ.

    Returns: [{"text": "...", "start": 0.0, "end": 1.5}, ...]
    """
    total_words = sum(len(p.split()) for p in phrases)
    timings = []
    current = 0.0
    for p in phrases:
        words = len(p.split())
        weight = words / total_words
        dur = total_duration * weight
        timings.append({
            "text": p,
            "start": current,
            "end": current + dur,
        })
        current += dur
    return timings


def render_subtitle_frames(
    text: str,
    audio_duration: float,
    aspect_ratio: str,
    output_dir: Path,
    fps: int = 30,
    font_path: Path | None = None,
) -> Path:
    """
    Render subtitle PNG sequence.

    Pattern: copy từ Parenting Tips render_subtitle_frames() —
    nhưng dùng phrase-level timing thay word-level.

    For each frame:
    - Determine current phrase pair (2 lines screen)
    - Within pair, highlight phrase đang đọc → vàng
    - Phrase chưa đọc → trắng
    """
    canvas = {"16:9": (1920, 1080), "9:16": (1080, 1920)}[aspect_ratio]
    W, H = canvas

    # Step 1: split text → phrases
    phrases = split_text_to_phrases(text, max_words=SUB_PHRASE_SIZE)

    # Step 2: estimate timings
    timings = estimate_phrase_timings(phrases, audio_duration)

    # Step 3: pair phrases (2 lines/screen)
    pairs = []
    for i in range(0, len(timings), 2):
        pair = [timings[i]]
        if i + 1 < len(timings):
            pair.append(timings[i + 1])
        pairs.append(pair)

    # Step 4: render frames (copy logic Parenting Tips)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    font = ImageFont.truetype(str(font_path), SUB_FONT_SIZE) if font_path else None

    total_frames = int(audio_duration * fps)
    y_center = int(H * SUB_POSITION_Y)
    y_line1 = y_center - SUB_FONT_SIZE - LINE_GAP // 2
    y_line2 = y_center + LINE_GAP // 2

    for frame_idx in range(total_frames):
        t = frame_idx / fps

        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Find active pair
        active_pair = None
        for pair in pairs:
            pair_start = pair[0]["start"]
            pair_end = pair[-1]["end"] + 0.3
            if pair_start <= t <= pair_end:
                active_pair = pair
                break

        if active_pair:
            # Draw line 1 (top)
            _draw_phrase(draw, active_pair[0], y_line1, t, font, W)
            # Draw line 2 (bottom) if exists
            if len(active_pair) > 1:
                _draw_phrase(draw, active_pair[1], y_line2, t, font, W)

        img.save(output_dir / f"frame_{frame_idx:05d}.png")

    return output_dir


def _draw_phrase(draw, phrase, y, t, font, W):
    """
    Draw 1 phrase, highlight vàng nếu t đã trong [phrase.start, phrase.end].
    """
    text = phrase["text"]
    is_active = phrase["start"] <= t <= phrase["end"] + 0.1
    color = COLOR_READ if is_active else COLOR_UNREAD

    # Center horizontally
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    x = (W - text_w) // 2

    # Shadow
    draw.text((x + 2, y + 2), text, fill=COLOR_SHADOW, font=font)
    # Main
    draw.text((x, y), text, fill=color, font=font)
```

---

## 11. UI + Workers — `ui/`, `workers/`

**REFERENCE**: SPEC.md mục 12 (UI specification) + mục 13 (Worker pattern).

Build theo pattern PyQt6 monolithic, không cần polling. Qt signal cho UI
realtime + atomic write state.json cho persistence.

### 11.1. UI structure

```
ui/
├── main_window.py          # Main window
├── connection_panel.py     # CDP connect
├── settings_panel.py       # Project settings
├── scene_list.py           # Scrollable list scene rows
├── scene_row.py            # 1 dòng/scene 40px
└── dialogs/
    ├── preview_image.py
    ├── preview_video.py
    ├── prompt_editor.py
    └── voice_import.py     # Wizard sinh voice_mapping.json
```

### 11.2. Voice import dialog (mới, đặc biệt cho phase này)

`ui/dialogs/voice_import.py`:

```
┌──────────────────────────────────────────┐
│ Import Voice Files               [×]     │
├──────────────────────────────────────────┤
│ Step 1: Select voice files               │
│ [Browse...] D:/voices/*.mp3              │
│ Found: voice_01.mp3, voice_02.mp3        │
│                                           │
│ Step 2: Assign scenes to each file       │
│                                           │
│ ▾ voice_01.mp3 (~25s)                    │
│   ☑ SCENE-01    ☑ SCENE-02    ☑ SCENE-03 │
│   ☐ SCENE-04    ☐ SCENE-05               │
│                                           │
│ ▾ voice_02.mp3 (~35s)                    │
│   ☐ SCENE-01    ☐ SCENE-02   ☐ SCENE-03  │
│   ☑ SCENE-04    ☑ SCENE-05               │
│                                           │
│ Validation:                               │
│ ✓ All 5 scenes assigned                  │
│                                           │
│        [Cancel]    [Save voice_mapping]   │
└──────────────────────────────────────────┘
```

UI logic:
- User browse folder/files mp3
- Form gán scenes cho mỗi file
- Validation: mỗi scene phải được assign vào 1 file (không 2)
- Click Save → ghi `voice_mapping.json`

### 11.3. Workers

```
workers/
├── batch_image.py          # gen all images
├── single_image.py         # re-gen 1 ảnh
├── batch_video.py          # gen all videos
├── single_video.py         # re-gen 1 video
├── slideshow_worker.py     # wrap slideshow_v4
├── ken_burns_worker.py     # Ken Burns render
├── voice_split_worker.py   # voice_split (KHÔNG có voice_gen, vì user gen ngoài)
├── subtitle_worker.py      # render subtitle PNG
└── final_video_worker.py   # composite + assemble + bgm
```

---

## 12. Estimator + State Writer

### 12.1. `runtime/state_writer.py`

**REFERENCE**: Copy 100% từ `D:\Projects\gen_video_grok\grok-story-factory\pipeline_state.py`.

Pattern: ghi `pipeline_state.json` mỗi khi task start/done/error.

### 12.2. `runtime/estimator.py`

**REFERENCE**: Copy 100% từ `D:\Projects\gen_video_grok\grok-story-factory\estimator.py`.

Self-improving baseline từ `timing_history.jsonl`.

---

## 13. Test plan từng phase

### Phase 1A: Schema + Core
```bash
# Test schema validation
python -c "
from core.schema import ScenesJson
import json
s = ScenesJson(**json.load(open('examples/scenes_voice_test.json')))
assert len(s.scenes) == 6
print('OK')
"
```

### Phase 1B: Engines (cần Brave debug)
```bash
# Manual test gen 1 image
python -c "
import asyncio
from engines.grok.engine import GrokEngine
# (mock scene, gen, verify file exists)
"
```

### Phase 1C: Render (offline)
```bash
# Test Ken Burns
python -c "
from render.ken_burns import ken_burns_self
import asyncio
asyncio.run(ken_burns_self(
    Path('test.jpg'),
    Path('out.mp4'),
    duration_sec=5,
    aspect_ratio='16:9',
))
"
```

### Phase 2: Voice + Subtitle
```bash
# Test voice split với file mp3 mẫu
python -c "
from voice.voice_split import split_audio_file
result = split_audio_file(
    Path('test_voice.mp3'),
    ['SCENE-01', 'SCENE-02', 'SCENE-03'],
    Path('voice/'),
)
assert len(result['scene_files']) == 3
print('OK')
"
```

### Phase 3: UI integration
- Load JSON
- Click batch image
- Watch UI update realtime
- Restart app → restore state OK

### Phase 4: Full pipeline E2E
- 1 project test: 6 scenes
- Gen ảnh → make video → import voice → split → make full
- Verify final.mp4 chạy được trên VLC, MPC-HC

---

## 14. Build instructions cho Claude Code

Bro paste prompt sau cho Claude Code:

```
You are continuing development of "Story Video Maker" PyQt6 app at:
    D:\Projects\story_video_making\

Context files to read first:
- D:\Projects\story_video_making\SPEC.md (architecture overview)
- D:\Projects\story_video_making\MIGRATION_PLAN.md (this file - build order)
- D:\Projects\gen_video_grok\ (READ-ONLY reference, production patterns)

Current state:
- Foundation done: core/, slideshow_v4/, voice/fish_tts.py
- Need to build: engines/grok/, render/, ui/, workers/, runtime/

Build order: follow MIGRATION_PLAN.md section 1 table.
Start with module #1 (Schema update). After each module:
1. Show file structure created
2. Run test from MIGRATION_PLAN section 13
3. Pause and wait for me to confirm before continuing

Important:
- Schema CHANGED: voice_batch_id and emotion fields REMOVED.
- voice_mapping.json is SEPARATE from scenes.json.
- Use Vietnamese for UI labels and log messages, English for code.
- Atomic write for state.json (tmp + rename).
- Reference D:\Projects\gen_video_grok\ for patterns but write NEW code,
  do NOT copy files directly.
```

---

## 15. Files cần update sau khi build xong

Sau khi xong Sprint 1:

1. **SPEC.md** — update mục 4 (schema mới, bỏ voice_batch_id + emotion)
2. **examples/scenes_voice_test.json** — bỏ voice_batch_id field
3. **examples/voice_mapping_example.json** — tạo mới làm template
4. **README.md** — viết hướng dẫn user

---

## 16. Tools đã sẵn sàng (KHÔNG động vào)

Các module/tool này đã hoàn chỉnh, build mới CÓ THỂ import nhưng KHÔNG sửa:

| Module | Vai trò |
|---|---|
| `voice/fish_tts.py` | Tool standalone gen TTS (user dùng ngoài app khi cần) |
| `slideshow_v4/` | Module Slideshow infographic, copy nguyên |
| `examples/scenes_voice_test.json` | Test data EN |

---

## End of Migration Plan

**Next action**: Bro giải nén `gen_video_grok.rar` ra `D:\Projects\gen_video_grok\`,
sau đó paste prompt mục 14 cho Claude Code.

Build dự kiến: 3-5 phiên Claude Code, mỗi phiên 1-2 module.
