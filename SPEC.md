# Story Video Maker — Architecture Specification

> **Purpose**: Spec đầy đủ để Claude Code build app PyQt6 desktop tự động hóa
> pipeline tạo video kể chuyện ngắn từ kịch bản JSON, kết hợp Grok image/video gen
> + Fish Audio TTS + Slideshow + Ken Burns + ffmpeg composite.
>
> **Reader**: Claude Code AI sẽ đọc file này để build app từ scratch hoặc maintain.
>
> **Status**: P0 spec — chuẩn bị Sprint 1.

---

## Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Tech stack](#2-tech-stack)
3. [Folder structure](#3-folder-structure)
4. [Schema scenes.json](#4-schema-scenesjson)
5. [Runtime state.json](#5-runtime-statejson)
6. [Engine Adapter Pattern](#6-engine-adapter-pattern)
7. [Voice pipeline](#7-voice-pipeline)
8. [Visual types & Render](#8-visual-types--render)
9. [Subtitle](#9-subtitle)
10. [BGM](#10-bgm)
11. [Final composite + assemble](#11-final-composite--assemble)
12. [UI specification](#12-ui-specification)
13. [Worker pattern](#13-worker-pattern)
14. [Warning system](#14-warning-system)
15. [Estimator + Debug](#15-estimator--debug)
16. [Sprints](#16-sprints)
17. [Coding conventions](#17-coding-conventions)

---

## 1. Tổng quan

### Pipeline tổng

```
[scenes.json - kịch bản]
       ↓
[Sprint 1] Gen images (Grok) → preview → re-gen từng ảnh nếu cần
       ↓
[Sprint 1] Per-scene: chọn make video Grok / Slideshow / Ken Burns
       ↓
[Sprint 2] Voice (Fish Audio batch + silence split) + Subtitle render
       ↓
[Sprint 3] User tick chọn source per scene → Composite + Assemble + BGM
       ↓
[final.mp4]
```

### Use case chính

User là content creator làm video kể chuyện ngắn (60s - 10 phút), 9:16 hoặc 16:9.
Workflow:

1. Viết kịch bản qua Claude Chat → output `scenes.json` (theo schema mục 4)
2. Mở app → load file → batch gen images Grok → preview → re-gen nếu cần
3. Per-scene: chọn make video Grok HOẶC slideshow (cho infographic) HOẶC Ken Burns
4. Gen voice (Fish Audio TTS) → cắt theo scene
5. Tick chọn visual source (image/video) cho từng scene
6. Make full video → ffmpeg ghép + BGM auto-pick → output mp4

### Use case phụ

- User load voice ngoài (recording, ElevenLabs gen sẵn) → app vẫn split được bằng silence detection
- User edit prompt từng scene trong UI rồi re-gen
- App restart giữa chừng → restore đúng trạng thái mỗi scene

### Phạm vi KHÔNG làm

- ❌ Không spawn browser mới — User tự chạy Brave/Chrome với debug port
- ❌ Không upload video lên YouTube/TikTok — chỉ output local mp4
- ❌ Không multi-user — single-user desktop app
- ❌ Không real-time streaming — batch processing only

---

## 2. Tech stack

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Async support, owner preferred |
| UI | PyQt6 | Mature, owner experience |
| Browser automation | Patchright (async Playwright fork) | Undetected, CDP attach |
| Async-Qt bridge | qasync | Required cho asyncio + Qt |
| Schema validation | Pydantic v2 | Type-safe JSON |
| Logging | loguru | Better than stdlib |
| Package manager | uv | Fast, reliable |
| TTS | fish-audio-sdk | Cao chất lượng VN |
| Image processing | Pillow + OpenCV | Slideshow + subtitle render |
| Video | ffmpeg (subprocess) | Industry standard |
| AI vision pick | Claude Code CLI subprocess | Free with subscription |
| Notifications | plyer (optional) | Cross-platform |

---

## 3. Folder structure

```
story_video_maker/
├── main.py                    # PyQt6 entry point
├── pyproject.toml
├── README.md
├── SPEC.md                    # This file
├── launch_brave.bat           # Brave debug launcher
│
├── core/
│   ├── __init__.py
│   ├── project.py             # Project class, load/save scenes.json + state
│   ├── schema.py              # Pydantic models
│   └── paths.py               # Path resolution utilities
│
├── engines/
│   ├── __init__.py
│   ├── base.py                # Protocol: ImageEngine, VideoEngine
│   └── grok/
│       ├── __init__.py
│       ├── selectors.py       # All Grok DOM selectors (centralized)
│       ├── browser.py         # CDP connect + tab management
│       ├── actions.py         # Atomic actions
│       ├── flows.py           # Declarative flow definitions
│       ├── runner.py          # Universal flow executor
│       └── claude_picker.py   # Vision-based pick best image
│
├── voice/
│   ├── __init__.py
│   ├── fish_tts.py            # ✅ Module 1: gen TTS batch (CÓ SẴN)
│   ├── voice_split.py         # Module 2: silence detection split batch → scene
│   └── voice_validator.py     # Validate voice files khớp scene count
│
├── render/
│   ├── __init__.py
│   ├── ken_burns.py           # Ken Burns self + continuation
│   ├── slideshow.py           # Wrap offline slideshow logic
│   ├── composite.py           # Composite 1 scene: visual + subtitle + audio
│   ├── assemble.py            # Final concat hard-cut
│   ├── subtitle.py            # Pillow karaoke render
│   └── filter_complex.py      # ffmpeg filter builder helpers
│
├── slideshow/                 # Offline slideshow pipeline
│   ├── preprocess.py          # Chroma key + rembg + dilate
│   ├── animations.py          # 6 animations
│   ├── claude_runner.py       # Subprocess Claude Code
│   └── renderer.py            # ffmpeg filter_complex builder
│
├── bgm/
│   ├── __init__.py
│   ├── picker.py              # Claude subprocess chọn BGM
│   └── mixer.py               # ffmpeg mix volume + fade
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py         # MainWindow
│   ├── connection_panel.py    # CDP connect UI
│   ├── settings_panel.py      # Project settings
│   ├── scene_list.py          # Scrollable list of scene rows
│   ├── scene_row.py           # 1 dòng/scene widget
│   ├── log_panel.py           # Bottom log + status
│   └── dialogs/
│       ├── preview_image.py   # Phóng to ảnh
│       ├── preview_video.py   # Play video
│       ├── prompt_editor.py   # Edit prompt modal
│       └── voice_source.py    # Chọn voice source dialog
│
├── workers/
│   ├── __init__.py
│   ├── batch_image.py         # QThread gen all images
│   ├── batch_video.py         # QThread gen all videos
│   ├── single_image.py        # QThread re-gen 1 ảnh
│   ├── single_video.py        # QThread re-gen 1 video
│   ├── slideshow_worker.py    # Wrap offline slideshow render
│   ├── ken_burns_worker.py    # Ken Burns render
│   ├── voice_worker.py        # Gen voice + split
│   └── final_video.py         # Make full video
│
├── runtime/
│   ├── __init__.py
│   ├── estimator.py           # Time estimator
│   └── timing_history.py      # Self-improving baseline
│
├── examples/
│   ├── scenes_voice_test.json
│   ├── scenes_template_simple.json
│   └── bgm_index_example.json
│
└── projects/                  # User projects (gitignored)
    └── {project_name}/
        ├── scenes.json        # Author-facing schema
        ├── state.json         # Runtime state (app-managed)
        ├── sources/
        │   ├── pic1.jpg ... picN.jpg
        │   └── vid1.mp4 ... vidN.mp4
        ├── voice/
        │   ├── batch_1.mp3 ... batch_N.mp3
        │   ├── manifest.json
        │   └── scene_1.mp3 ... scene_N.mp3
        ├── bgm/
        │   ├── chosen.json
        │   └── mixed.mp3
        ├── temp/              # Composite intermediate
        └── final.mp4
```

---

## 4. Schema scenes.json

### 4.1. Cấu trúc

```json
{
  "version": "1.0",
  "meta": { ... },
  "settings": { ... },
  "scenes": [ ... ]
}
```

### 4.2. Top-level fields

| Field | Type | Required | Mô tả |
|---|---|---|---|
| `version` | string | ✅ | "1.0" — schema version |
| `meta.project_id` | string | ✅ | Định danh unique |
| `meta.title` | string | ✅ | Hiển thị trong UI |
| `meta.aspect_ratio` | "16:9" \| "9:16" | ✅ | Output format |
| `meta.language` | "vi" \| "en" | ✅ | Default voice + subtitle |
| `settings.baseStyle` | string | ✅ | Style chung tất cả ảnh (vd: "Simple flat 2D illustration...") |
| `settings.baseNegative` | string | ✅ | Negative prompt chung |
| `settings.topic` | string | ✅ | Cho Claude pick BGM + claude pick image context |
| `settings.voice_model_id` | string | optional | Fish Audio voice ID, override per project |
| `settings.voice_speed` | float | optional | Default 1.0 |
| `settings.image_quality` | "speed" \| "quality" | ✅ | Grok preset |
| `settings.video_resolution` | "480p" \| "720p" | ✅ | Grok video |
| `settings.video_duration` | "6s" \| "10s" | ✅ | Grok video |

### 4.3. Per-scene fields (7 fields chính)

```json
{
  "id": "SCENE-01",
  "voice_batch_id": 1,
  "visual_type": "Image",
  "story_vi": "Buổi sáng. Căn bếp còn ngủ. Chỉ có tiếng nước sôi nhẹ trong ấm.",
  "imagePrompt": "...",
  "videoPrompt": "...",
  "duration": 10
}
```

| Field | Type | Required | Mô tả |
|---|---|---|---|
| `id` | string | ✅ | Unique scene ID, dùng làm key trong state |
| `voice_batch_id` | int | ✅ | User chia thủ công group voice TTS |
| `visual_type` | enum | ✅ | Xem mục 8.1 |
| `story_vi` (or `story_en`) | string | ✅ | Script đọc + subtitle |
| `imagePrompt` | string | ✅ | Prompt gen Grok image |
| `videoPrompt` | string \| null | optional | Prompt gen Grok video. null = chỉ làm ảnh |
| `duration` | int | ✅ | Gợi ý duration (giây). Final tự khớp voice |

### 4.4. visual_type enum

```
"Image"       → Still image scene; provider/model được chọn ở project/task level
"Video"       → Model-generated video scene; provider/model được chọn ở project/task level
"slideshow"   → Offline slideshow/render-tool flow, không thuộc provider/model
```

Legacy aliases được accept khi load và normalize khi save:

```
"image_grok" / "image" → "Image"
"video_grok" / "video" → "Video"
```

### 4.5. Validation (Pydantic schema)

Implement trong `core/schema.py`:

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
    voice_model_id: str | None = None
    voice_speed: float = 1.0
    image_quality: Literal["speed", "quality"] = "quality"
    video_resolution: Literal["480p", "720p"] = "720p"
    video_duration: Literal["6s", "10s"] = "10s"

class Scene(BaseModel):
    id: str
    voice_batch_id: int = Field(ge=1)
    visual_type: Literal["Image", "Video", "slideshow"]
    story_vi: str | None = None
    story_en: str | None = None
    imagePrompt: str
    videoPrompt: str | None = None
    duration: int = Field(ge=1, le=60)

    def get_story(self, lang: str) -> str:
        return self.story_vi if lang == "vi" else self.story_en

class ScenesJson(BaseModel):
    version: Literal["1.0"]
    meta: Meta
    settings: Settings
    scenes: list[Scene]
```

---

## 5. Runtime state.json

**Tách riêng khỏi scenes.json** — author-facing JSON sạch, runtime state quản lý độc lập.

### Path

`projects/{project_name}/state.json`

### Schema

```json
{
  "version": 1,
  "updated_at": "2026-04-27T10:30:00",
  "image_refs": ["D:/photos/character.png", "D:/photos/style.png"],
  "use_refs_for_image": true,
  "scenes": {
    "SCENE-01": {
      "image": {
        "status": "ready",
        "path": "sources/pic1.jpg",
        "last_gen_at": "2026-04-27T10:00:00",
        "fail_reason": null
      },
      "video": {
        "status": "ready",
        "path": "sources/vid1.mp4",
        "source_type": "grok",
        "last_gen_at": "2026-04-27T10:15:00"
      },
      "voice": {
        "status": "ready",
        "path": "voice/scene_1.mp3",
        "duration_sec": 4.23
      },
      "selected_visual": "video",
      "warnings": []
    },
    "SCENE-02": { ... }
  }
}
```

**Project-level fields** (added Sprint 3):
- `image_refs: list[str]` — absolute paths of reference images (max 5) for image-with-refs flow.
- `use_refs_for_image: bool` — when true, `BatchImageWorker` / `SingleImageWorker` route through `GrokImageRefEngine` (linear single-result) instead of the masonry `GrokImageEngine`. Empty list with flag on → log warning + fallback to masonry.

### Status enum

```
"pending"     → chưa bắt đầu
"generating"  → đang chạy
"ready"       → done OK
"failed"      → fail, có fail_reason
```

### source_type enum (cho video)

```
"grok"            → provider source for generated Image/Video assets
"slideshow"       → offline slideshow render source
```

### selected_visual enum

```
null         → user chưa chọn (default = ảnh nếu có)
"image"      → dùng ảnh tĩnh + Ken Burns lúc final
"video"      → dùng video làm visual
```

### Behavior

- App load `scenes.json` → tạo/đọc `state.json` tương ứng
- Mỗi update state → ghi `state.json` ngay (atomic write: tmp + rename)
- Backup rotate: `state.json.bak.{timestamp}` giữ 5 file gần nhất
- App crash → mở lại đọc state.json → restore status icon đúng

### Atomic write pattern

```python
def save_state_atomic(path: Path, data: dict):
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic rename
```

---

## 6. Engine Adapter Pattern

**Mục tiêu**: Khi Grok đổi DOM hoặc swap sang ChatGPT image, chỉ sửa file engine, không động orchestrator/UI/voice/render.

### `engines/base.py` — Protocols

```python
from typing import Protocol
from pathlib import Path

class ImageEngine(Protocol):
    async def gen_image(
        self,
        prompt: str,
        settings: dict,
        ref_image: Path | None = None
    ) -> Path:
        """Trả về path file ảnh đã download."""
        ...

    async def pick_best(
        self,
        candidates: list[Path],
        prompt: str,
        topic: str,
        style: str
    ) -> int:
        """Trả về index ảnh best."""
        ...

class VideoEngine(Protocol):
    async def gen_video(
        self,
        prompt: str,
        ref_image: Path,
        settings: dict
    ) -> Path:
        """Image-to-Video. Trả về path mp4."""
        ...

class EngineConnection(Protocol):
    async def connect(self, cdp_url: str) -> None: ...
    async def disconnect(self) -> None: ...
    async def is_connected(self) -> bool: ...
```

### `engines/grok/` — Implementation

**Phải implement đủ**:
- `GrokImageEngine` — implements ImageEngine (masonry + Claude pick, used when no refs)
- `GrokImageRefEngine` — image-with-refs linear flow (1-5 reference uploads, single result, video-style 30s wait pattern)
- `GrokVideoEngine` — implements VideoEngine
- `GrokConnection` — implements EngineConnection

**Pattern bên trong**:
- Centralize all selectors trong `selectors.py`
- Atomic actions trong `actions.py` (set_mode, fill_prompt, click_submit, wait_*, download)
- Declarative flows trong `flows.py` (text_to_image, image_to_image, text_to_video, image_to_video)
- `runner.py` execute flow steps + state machine

**Reference**: Logic Grok automation đã được spec trong file `MASTER_grok_automation.md`. Claude Code đọc file đó để hiểu DOM selectors, flow actions, error handling. **KHÔNG copy nguyên code** — refactor thành adapter pattern theo Protocol trên.

### `engines/grok/claude_picker.py` — Mở rộng

Hiện tại `claude_picker.py` chỉ pick "đẹp nhất". Mở rộng prompt template để truyền topic + style:

```python
async def pick_best(
    candidates: list[Path],
    prompt: str,
    topic: str,
    style: str
) -> int:
    instruction = f"""Pick ảnh sát nhất với prompt VÀ giữ tính nhất quán style toàn project.

PROJECT TOPIC: "{topic}"
PROJECT STYLE: "{style}"
SCENE PROMPT: "{prompt}"

Tiêu chí (priority order):
1. Style phải match project style ({style}) — quan trọng nhất
2. Match prompt scene
3. Composition đẹp, không lỗi

Trả về JSON: {{"choice": 0-3, "rationale": "..."}}
"""
    # subprocess call Claude Code CLI...
```

---

## 7. Voice pipeline

### 7.1. Flow tổng

```
[scenes.json]
    ↓
[fish_tts.py]      ← Module 1: gen TTS batch
    ↓
voice/batch_*.mp3 + manifest.json
    ↓
[voice_split.py]   ← Module 2: silence detection
    ↓
voice/scene_*.mp3
```

### 7.2. Module 1: `voice/fish_tts.py` (ĐÃ CÓ)

**Input**: scenes.json
**Output**: `voice/batch_{N}.mp3` + `voice/manifest.json`

**Logic**:
1. Group scenes theo `voice_batch_id`
2. Mỗi batch: ghép `story_vi` của các scenes → 1 text dài (separator = " ")
3. Call `fish_audio_sdk.tts.convert(text=joined, reference_id=voice_id)`
4. Save mp3 + write manifest

**Manifest format** (xem `fish_tts.py` đã có).

**Configurable**:
- `--voice-id`: override `settings.voice_model_id`
- `--speed`: tốc độ đọc
- `--force`: re-gen ngay cả khi file đã có
- API key: env `FISH_API_KEY` hoặc `--api-key`

### 7.3. Module 2: `voice/voice_split.py` (CHƯA LÀM)

**Input**: `voice/batch_*.mp3` + `manifest.json`
**Output**: `voice/scene_{id}.mp3` cho từng scene + update state.json

**Algorithm**:

```
For each batch in manifest:
    1. Load batch_{N}.mp3
    2. Run ffmpeg silencedetect:
       ffmpeg -i batch_N.mp3 -af "silencedetect=n=-30dB:d=0.3" -f null -

    3. Parse stderr → list of silence intervals:
       [{"start": 2.45, "end": 2.78}, {"start": 5.12, "end": 5.50}, ...]

    4. Compute boundary timestamps (giữa silence là cut point):
       boundaries = [(silence.start + silence.end) / 2 for silence in silences]

    5. Match boundaries với số scenes trong batch:
       - Nếu len(boundaries) == len(scenes_in_batch) - 1: PERFECT
       - Nếu lệch: pick top-N silence dài nhất
       - Nếu vẫn không khớp: emit warning, fallback equal split

    6. Cut bằng ffmpeg:
       For i, scene in enumerate(scenes_in_batch):
           start = boundaries[i-1] if i > 0 else 0
           end = boundaries[i] if i < len(scenes_in_batch)-1 else duration
           ffmpeg -i batch_N.mp3 -ss {start} -to {end} -c copy scene_{id}.mp3

    7. Update state.json: voice.status = "ready", voice.path, voice.duration_sec
```

**Edge cases**:
- Batch chỉ có 1 scene → copy nguyên batch.mp3 → scene_{id}.mp3, không cần split
- Silence detection trả 0 boundaries cho batch nhiều scenes → warning + emit signal cho UI hiện waveform để user click manual
- File mp3 không tồn tại → error

**Manual fallback UI** (Sprint 2 nếu cần):
- Dialog hiện waveform của batch_N.mp3
- User click N-1 boundary points
- App cắt theo điểm user click

### 7.4. VoiceSource Protocol (tương lai-proof)

```python
class VoiceSource(Protocol):
    async def get_audio_for_scene(self, scene_id: str) -> Path:
        """Trả về path scene_{id}.mp3"""
        ...

    async def get_duration(self, scene_id: str) -> float:
        """Trả về duration giây"""
        ...
```

Implementations:
- `FishAudioVoice` — gen TTS từ Fish Audio
- `ExternalVoice` — load file user upload, dùng voice_split để cắt

---

## 8. Visual types & Render

### 8.1. visual_type → render module

| visual_type | Workflow | Output | Module |
|---|---|---|---|
| `Image` | Gen still image via selected provider/model → save ảnh | sources/pic{N}.jpg | provider worker |
| `Video` | Gen video via selected provider/model → save video | sources/vid{N}.mp4 | provider worker |
| `slideshow` | Offline slideshow/render-tool flow | sources/vid{N}.mp4 | render/slideshow.py wrap |

### 8.2. `render/slideshow.py` — Wrap offline slideshow

```python
async def render_slideshow(
    image_path: Path,        # ảnh có bg đơn + objects
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str,
    hint: str = ""
) -> Path:
    """Wrap slideshow main pipeline."""
    # Call slideshow với image_path, duration, preset
    # Return output_path
```

### 8.4. Per-scene composite (`render/composite.py`)

Compose 1 scene thành mp4 hoàn chỉnh: visual + subtitle PNG sequence + voice audio.

```python
async def composite_scene(
    visual_path: Path,        # ảnh hoặc video
    visual_type: str,         # để biết static hay animated
    voice_path: Path | None,
    subtitle_frames_dir: Path | None,
    duration_sec: float,      # = voice duration nếu có voice, else scene.duration
    aspect_ratio: str,
    output_path: Path
) -> Path:
    """
    ffmpeg pipeline:
    1. Visual layer:
       - Nếu image: scale + zoompan (Ken Burns subtle) + tpad nếu cần
       - Nếu video: scale + setpts (speed match) + freeze tail nếu cần
    2. Subtitle overlay (PNG sequence)
    3. Audio mux
    4. Output mp4
    """
```

**Speed match logic** (cho video clip):

```python
clip_dur = ffprobe(visual_path)
target_dur = voice_duration

ratio = clip_dur / target_dur

if 0.7 <= ratio <= 1.4:
    # OK stretch bằng setpts
    setpts_factor = ratio
elif ratio > 1.4:
    # Clip dài quá → trim
    use_trim = True
elif ratio < 0.7:
    # Clip ngắn quá → freeze last frame
    use_freeze_tail = True
    warning = "speed_stretch_high"
```

---

## 9. Subtitle

### 9.1. Style spec (copy từ Parenting Tips)

| Param | Value |
|---|---|
| Font | Montserrat-ExtraBold (bundle trong app) |
| Font size | 44px (16:9), 36px (9:16) |
| Position | 78%-88% từ top (default 85%) |
| Max lines | 2 |
| Max words/line | 5 |
| Color inactive | white (#FFFFFF) |
| Color active | yellow (#FFD700) — karaoke highlight word đang đọc |
| Shadow | 2px black offset (1, 1) |
| Background | None (transparent overlay) |

### 9.2. `render/subtitle.py`

**Input**:
- `story_vi` của scene
- voice timestamps (word-level từ Fish Audio ASR hoặc heuristic)
- duration_sec
- aspect_ratio

**Output**: `temp/subtitle_{scene_id}/frame_*.png` (PNG sequence 30fps, transparent bg)

**Algorithm**:

```
1. Tokenize story → words
2. Group words → phrases (max 5 từ/dòng, break tại punctuation hoặc gap)
3. Pair phrases → 2-line screens
4. For each frame (30fps):
   - Determine current screen (theo timestamp)
   - For each word in screen: white nếu chưa đọc, yellow nếu đang đọc, white sau khi đọc
   - Render PIL Image với 2 lines, position 85% from top
   - Save frame as PNG

Note: Nếu chưa có word-level timestamps (P3 chưa làm split với word align):
  → Fallback chia đều theo số word: word_i.timestamp = i / total * duration
  → Karaoke timing không 100% chính xác nhưng acceptable cho MVP
```

### 9.3. Composite subtitle vào scene

ffmpeg overlay PNG sequence:
```
ffmpeg -i visual.mp4 -framerate 30 -i temp/subtitle_SCENE-01/frame_%05d.png \
  -filter_complex "[0:v][1:v]overlay=x=0:y=0:format=auto[out]" \
  -map [out] -c:v libx264 -pix_fmt yuv420p output.mp4
```

---

## 10. BGM

### 10.1. BGM index JSON (user maintain)

**File**: `bgm/index.json` (user tự label thủ công 1 lần)

```json
{
  "version": 1,
  "bgm_folder": "D:/assets/BGM",
  "tracks": [
    {
      "file": "calm_morning_01.mp3",
      "duration_sec": 180,
      "genres": ["ambient", "lofi"],
      "emotions": ["calm", "peaceful", "warm"],
      "tempo": "slow",
      "intensity": 0.3,
      "has_vocals": false,
      "loop_friendly": true,
      "tags": ["morning", "coffee", "lifestyle", "warm"]
    },
    {
      "file": "uplifting_corp_01.mp3",
      "duration_sec": 180,
      "genres": ["corporate"],
      "emotions": ["uplifting", "energetic"],
      "tempo": "medium",
      "intensity": 0.6,
      "has_vocals": false,
      "loop_friendly": true,
      "tags": ["business", "explainer", "tech"]
    }
  ]
}
```

### 10.2. `bgm/picker.py`

```python
async def pick_bgm(
    topic: str,
    style: str,
    total_duration: float,
    bgm_index: dict
) -> dict:
    """
    Subprocess call Claude Code CLI.

    Prompt:
    "Topic: {topic}, Style: {style}, Duration: {total_duration}s.
     BGM index: {bgm_index}.
     Pick 1 track most fitting. Return JSON:
     {choice_file, volume_db, fade_in_sec, fade_out_sec, rationale}"
    """
    # Returns: {file, volume_db, fade_in, fade_out, rationale}
```

### 10.3. `bgm/mixer.py`

```python
async def mix_bgm(
    main_video: Path,         # video đã ghép tất cả scenes
    bgm_path: Path,
    volume_db: float = -22,   # relative to main audio
    fade_in_sec: float = 1.5,
    fade_out_sec: float = 2.0,
    output_path: Path = None
) -> Path:
    """
    ffmpeg mix:
    1. Get main video duration
    2. Loop bgm nếu ngắn hơn, hoặc trim nếu dài hơn
    3. Apply fade_in + fade_out + volume
    4. amix với main audio
    """
```

---

## 11. Final composite + assemble

### 11.1. Pipeline `make_full_video`

```
Pre-check:
  - Mỗi scene phải có selected_visual (image hoặc video) → block + UI highlight nếu thiếu
  - Voice optional (warn nếu thiếu, không block)

For each scene:
  1. Determine visual:
     - selected_visual == "video" → sources/vid{N}.mp4
     - selected_visual == "image" → sources/pic{N}.jpg
  2. Determine voice: voice/scene_{id}.mp3 (nếu có)
  3. Generate subtitle PNG sequence (nếu có voice)
  4. Composite: visual + subtitle + voice → temp/scene_{id}.mp4
     Speed match logic ở mục 8.4

Assemble:
  1. Hard-cut concat tất cả temp/scene_{id}.mp4 → temp/main.mp4
     (KHÔNG xfade — gây freeze VLC)
  2. Pick BGM via Claude → bgm/chosen.json
  3. Mix BGM → final.mp4
```

### 11.2. `render/assemble.py`

```python
async def assemble_scenes(
    scene_videos: list[Path],
    output_path: Path,
    aspect_ratio: str
) -> Path:
    """
    Hard-cut concat. Normalize fps/resolution/sar/audio sample rate trước concat.

    1. Pre-process từng scene → consistent format:
       ffmpeg -i scene.mp4 -vf "scale={W}:{H},setsar=1,fps=30" \
         -ar 48000 -ac 2 normalized_scene.mp4

    2. Concat list:
       file 'normalized_scene_1.mp4'
       file 'normalized_scene_2.mp4'
       ...

    3. ffmpeg -f concat -safe 0 -i list.txt -c copy main.mp4
    """
```

### 11.3. Why hard-cut?

Parenting Tips report `xfade` gây **freeze VLC** khi play file đã encode. Hard-cut concat an toàn hơn.

Optional flag `--xfade` cho user thử nghiệm (đánh dấu experimental).

---

## 12. UI specification

### 12.1. MainWindow layout

```
┌──────────────────────────────────────────────────────────────┐
│  Story Video Maker                            [_][□][×]      │
├──────────────────────────────────────────────────────────────┤
│  ┌─ Connection ────────────────────────────────────────────┐ │
│  │ CDP URL: [http://localhost:9222]  [🔌 Connect]         │ │
│  │ Status: ● Connected  Tab: [▾ grok.com/imagine]         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌─ Project ──────────────────────────────────────────────┐ │
│  │ Project: [📂 Load scenes.json] morning_coffee_001       │ │
│  │ Topic: Buổi sáng cà phê    Aspect: 16:9    Lang: vi    │ │
│  │ Quality: ●Quality ○Speed   Voice: [▾ Default Fish ID]  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌─ Scenes (6) ───────────────────────────────────────────┐ │
│  │ [+ Batch Image] [+ Batch Video] [+ Voice] [+ Make Full]│ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ ☐ SCENE-01 ⏳ Image | 🖼️ ✓ | 🎬 ⏳ | 🎤 ⏳ |⚠ |🔍|✏ │ │
│  │ ☐ SCENE-02 ⏳ Video | 🖼️ ✓ | 🎬 ✓ | 🎤 ⏳ |  |🔍|✏ │ │
│  │ ☑ SCENE-03 ✓  slideshow | 🖼️ ✓ | 🎬 ✓ | 🎤 ✓ |  |🔍|✏ │ │
│  │ ...                                                      │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌─ Log ──────────────────────────────────────────────────┐ │
│  │ [scrollable]                                             │ │
│  │ [💾 Save state] [🗑 Clear log]                          │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 12.2. Scene row widget (40px height)

```
┌────────────────────────────────────────────────────────────────────┐
│ ☐ SCENE-01 ⏳ Image | 🖼️ ✓ | 🎬 ⏳ | 🎤 ⏳ | ⚠ | 🔍 | ✏️ │
└────────────────────────────────────────────────────────────────────┘
   │     │       │           │      │       │      │   │    │
   │     │       │           │      │       │      │   │    └─ Edit prompt button (modal)
   │     │       │           │      │       │      │   └─ Preview button (modal)
   │     │       │           │      │       │      └─ Warning indicator (icon)
   │     │       │           │      │       └─ Voice status icon
   │     │       │           │      └─ Video status icon
   │     │       │           └─ Image status icon
   │     │       └─ visual_type label
   │     └─ Overall scene status icon
   └─ Tick checkbox (selected_visual)

Status icons:
   ⏳ pending
   🔄 generating
   ✓ ready
   ❌ failed

Visual type labels:
   Image | Video | slideshow
```

**Click actions**:
- Tick: toggle `selected_visual` (image ↔ video)
- 🖼️: hover tooltip (path), click = preview modal
- 🎬: same
- 🎤: same (play audio)
- ⚠: tooltip warnings list, click = show details
- 🔍: preview modal cho ảnh + video
- ✏️: edit prompt modal

### 12.3. Edit prompt modal

```
┌──────────────────────────────────────────────────┐
│ Edit Prompts — SCENE-01              [×]        │
├──────────────────────────────────────────────────┤
│ Story (vi):                                       │
│ ┌────────────────────────────────────────────┐  │
│ │ Buổi sáng. Căn bếp còn ngủ...              │  │
│ └────────────────────────────────────────────┘  │
│                                                   │
│ Image Prompt:                                     │
│ ┌────────────────────────────────────────────┐  │
│ │ Simple flat 2D illustration of...          │  │
│ └────────────────────────────────────────────┘  │
│                                                   │
│ Video Prompt: ☐ Enable                            │
│ ┌────────────────────────────────────────────┐  │
│ │ (disabled)                                  │  │
│ └────────────────────────────────────────────┘  │
│                                                   │
│ Visual Type: [▾ Image]                            │
│ Voice Batch: [1]                                  │
│ Duration: [10]                                    │
│                                                   │
│         [Cancel]  [💾 Save & Re-gen]  [💾 Save]  │
└──────────────────────────────────────────────────┘
```

### 12.4. Preview modal

15% screen size (theo bro yêu cầu):
- Image: hiển thị ảnh full quality
- Video: HTML5 video player
- Path đầy đủ ở footer
- Button: "Open folder", "Re-gen"

### 12.5. Persistence

QSettings save:
- CDP URL
- Last project loaded
- Window size + position
- Default settings (quality, resolution, etc.)

### 12.6. Reference Images panel (Sprint 3)

`ui/refs_panel.py::RefImagesPanel` — sits beside the Log box (7:3 split, 280-400px clamp). Disabled until a project loads.

```
┌─ Reference Images (Image gen) ────────────┐
│ ☐ Use refs for image gen                   │
│ [📁 Browse...] (N/5)                       │
│ 1. character.png      [✗ Remove]           │
│ 2. style_ref.png      [✗ Remove]           │
└────────────────────────────────────────────┘
```

- Multi-select file dialog; capped at 5 entries
- Per-row remove button
- Toggle + list emit `refs_changed(paths, use_refs)` → `MainWindow._on_refs_changed` writes both fields to project state via `set_image_refs` / `set_use_refs_for_image`
- On project load, `set_state(paths, use_refs)` restores from `state.json`

### 12.7. Stop All button (Sprint 3)

`🛑 Stop All` (red) sits next to `■ Dừng` in the action row. Backed by `_active_workers: list` registry.

- Every `worker.start()` site calls `_register_worker(worker)`. The worker's `finished` signal auto-`_unregister_worker`.
- Click → confirm dialog with running-worker count → loop `request_stop()` on every entry.
- Idle click → info dialog "Không có worker nào đang chạy".
- Wrapped sites: `BatchImageWorker`, `BatchVideoWorker`, `SingleImageWorker`, `SingleVideoWorker` / `SlideshowWorker`, `VoiceAlignWorker`, `RenderWorker`, `ExportKdenliveWorker`.

---

## 13. Worker pattern

### 13.1. QThread + Signal

```python
from PyQt6.QtCore import QThread, pyqtSignal

class BatchImageWorker(QThread):
    # Signals
    scene_started = pyqtSignal(str)              # scene_id
    scene_finished = pyqtSignal(str, dict)       # scene_id, new_state
    scene_failed = pyqtSignal(str, str)          # scene_id, reason
    batch_progress = pyqtSignal(int, int)        # done, total
    batch_done = pyqtSignal()
    log = pyqtSignal(str)                        # log message

    def __init__(self, project, engine):
        super().__init__()
        self.project = project
        self.engine = engine
        self._stop = False

    def run(self):
        scenes = self.project.scenes
        for i, scene in enumerate(scenes):
            if self._stop:
                break
            try:
                self.scene_started.emit(scene.id)
                path = asyncio_run(self.engine.gen_image(...))

                # Update state + persist
                new_state = {"status": "ready", "path": str(path), "last_gen_at": now()}
                self.project.update_scene_state(scene.id, "image", new_state)

                self.scene_finished.emit(scene.id, new_state)
                self.batch_progress.emit(i+1, len(scenes))
            except Exception as e:
                self.project.update_scene_state(
                    scene.id, "image",
                    {"status": "failed", "fail_reason": str(e)}
                )
                self.scene_failed.emit(scene.id, str(e))

        self.batch_done.emit()

    def stop(self):
        self._stop = True
```

### 13.2. UI thread connect

```python
class MainWindow(QMainWindow):
    def start_batch_image(self):
        self.batch_worker = BatchImageWorker(self.project, self.grok_engine)
        self.batch_worker.scene_started.connect(self.on_scene_started)
        self.batch_worker.scene_finished.connect(self.on_scene_finished)
        self.batch_worker.scene_failed.connect(self.on_scene_failed)
        self.batch_worker.batch_progress.connect(self.on_batch_progress)
        self.batch_worker.log.connect(self.append_log)
        self.batch_worker.start()

    def on_scene_started(self, scene_id):
        row = self.scene_rows[scene_id]
        row.set_image_status("generating")

    def on_scene_finished(self, scene_id, new_state):
        row = self.scene_rows[scene_id]
        row.set_image_status("ready", new_state["path"])
```

### 13.3. asyncio + Qt bridge

Patchright là async API. Dùng `qasync`:

```python
# main.py
import asyncio
from qasync import QEventLoop, asyncSlot

app = QApplication(sys.argv)
loop = QEventLoop(app)
asyncio.set_event_loop(loop)

window = MainWindow()
window.show()

with loop:
    loop.run_forever()
```

Trong worker:
```python
def run(self):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(self._async_run())
    finally:
        loop.close()
```

---

## 14. Warning system

### 14.1. Warning types

| Code | Trigger | Severity | Action |
|---|---|---|---|
| `grok_no_image` | Gen image fail/timeout | High | Block use as visual, show "Retry" button |
| `grok_no_video` | Gen video fail/timeout | High | Suggest "Make slide instead" button |
| `voice_split_failed` | Silence detection không khớp boundaries | Medium | Suggest manual boundary picker |
| `speed_stretch_high` | Clip ratio out [0.7, 1.4] | Medium | Show ratio + recommend re-gen |
| `voice_missing` | Scene không có voice file | Low | Final video sẽ silent cho scene đó |
| `slideshow_no_objects` | slideshow không tách được object | High | Suggest switch sang `Image` |

### 14.2. UI

Per-scene row có icon ⚠ → tooltip list warnings → click = show full details modal.

Make Full button: pre-check warnings, nếu có severity High → confirm dialog.

### 14.3. Storage

Warnings lưu trong `state.json`:
```json
"warnings": [
  {"code": "speed_stretch_high", "msg": "Clip 6s, voice 10s, ratio 0.6", "ts": "..."},
  {"code": "grok_no_video", "msg": "Timeout sau 5 phút", "ts": "..."}
]
```

Warnings clear khi: re-gen thành công cho scene đó.

---

## 15. Estimator + Debug

### 15.1. `runtime/estimator.py`

```python
DEFAULT_BASELINES = {
    "gen_image": {"avg": 45, "p50": 40, "p90": 75, "p99": 120},
    "gen_video": {"avg": 180, "p50": 165, "p90": 240, "p99": 360},
    "slideshow_render": {"avg": 30, "p50": 25, "p90": 50, "p99": 90},
    "ken_burns_render": {"avg": 5, "p50": 4, "p90": 8, "p99": 15},
    "voice_gen_per_100chars": {"avg": 3, "p50": 2.5, "p90": 5, "p99": 10},
}

class Estimator:
    def __init__(self, history_path: Path):
        self.history_path = history_path
        self.baselines = self._load_or_default()

    def estimate_batch(self, scenes: list, action: str) -> dict:
        """
        Returns: {avg_sec, p90_sec, formatted_avg, formatted_p90}
        """
        n = len(scenes)
        b = self.baselines[action]
        return {
            "avg_sec": n * b["avg"],
            "p90_sec": n * b["p90"],
            "formatted_avg": f"~{n * b['avg'] / 60:.0f} min",
            "formatted_p90": f"P90: ~{n * b['p90'] / 60:.0f} min",
        }

    def record_actual(self, action: str, duration_sec: float):
        """Append vào history JSONL, rolling update baseline mỗi 20 records."""
        ...
```

### 15.2. UI hiển thị estimate

```
[+ Batch Image (50 scenes)]
   Estimate: ~38 min (P90: 62 min)
   [Confirm]
```

### 15.3. Debug screenshot

Trong `engines/grok/actions.py`:
```python
async def safe_action(action_name, page, fn):
    try:
        return await fn()
    except Exception as e:
        # Screenshot for debugging
        debug_dir = Path("projects/_debug") / action_name
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = debug_dir / f"{action_name}_{ts}.png"
        try:
            await page.screenshot(path=str(screenshot_path))
        except:
            pass
        log.error(f"{action_name} failed: {e}, screenshot: {screenshot_path}")
        raise
```

---

## 16. Sprints

### Sprint 1 — Grok full pipeline (P1 + P2 merged)

**Mục tiêu**: User load scenes.json → batch gen images → re-gen từng ảnh → make video Grok / Slideshow / Ken Burns per scene → preview → state persist OK.

**Modules cần build**:
- `core/project.py`, `core/schema.py`
- `engines/base.py`, `engines/grok/*` (full implementation từ MASTER_grok_automation.md)
- `render/ken_burns.py`
- `render/slideshow.py` (wrap offline slideshow)
- `slideshow/` external pipeline
- `workers/batch_image.py`, `single_image.py`, `batch_video.py`, `single_video.py`, `slideshow_worker.py`, `ken_burns_worker.py`
- `ui/main_window.py`, `scene_list.py`, `scene_row.py`, `connection_panel.py`, `dialogs/*`
- `runtime/estimator.py`

**Test exit criteria**:
- Load scenes_template_simple.json → UI hiện 6 dòng scene
- Click "Batch Image" → 6 ảnh gen xong, status icon đổi đúng
- Re-gen 1 scene → ảnh đó update, các scene khác không động
- Switch visual_type SCENE-03 sang `slideshow` → render slideshow ra vid3.mp4
- Đóng app, mở lại → status đúng như lúc đóng
- Warning hiển thị khi 1 scene fail

### Sprint 2 — Voice + Subtitle

**Mục tiêu**: Gen voice batch → split scene → render subtitle PNG sequence.

**Modules**:
- `voice/fish_tts.py` (đã có)
- `voice/voice_split.py`
- `voice/voice_validator.py`
- `render/subtitle.py`
- `workers/voice_worker.py`

**Test exit criteria**:
- Click "Voice Gen" → batch_*.mp3 sinh ra
- Click "Voice Split" → scene_*.mp3 sinh ra (silence detection OK với batch 1-2 scenes)
- Manual fallback nếu split fail
- Subtitle PNG sequence sinh ra cho mỗi scene
- Karaoke timing acceptable (chưa cần 100% perfect)

### Sprint 3 — Composite + Assemble + BGM

**Mục tiêu**: Make full video.

**Modules**:
- `render/composite.py`
- `render/assemble.py`
- `bgm/picker.py`, `bgm/mixer.py`
- `workers/final_video.py`

**Test exit criteria**:
- Pre-check pass khi đủ visual selected
- Composite từng scene OK
- Assemble hard-cut OK, play VLC không freeze
- BGM auto-pick + mix OK
- Final.mp4 player được, đủ scenes, đúng aspect ratio, voice + subtitle khớp

---

## 17. Coding conventions

### Language

- **User-facing**: Vietnamese (UI, log, error messages)
- **Code, comments, docstrings, commits**: English
- **Variable names**: English

### Async style

- Patchright: async
- ffmpeg: subprocess (sync trong worker thread)
- Subprocess Claude CLI: sync subprocess.run

### Error handling

```python
# Don't crash UI:
try:
    result = await action()
except Exception as e:
    log.error(f"Action failed: {e}")
    return {"ok": False, "reason": str(e)}

# DO raise from atomic actions for runner to catch:
async def some_action():
    if not condition:
        raise RuntimeError("Specific reason")
```

### State management

- All scene state trong `project.state` dict (mirror state.json)
- No globals
- Atomic write pattern cho state.json
- Backup rotate `.bak.{timestamp}`

### Logging

```python
from loguru import logger as log

log.debug("Detailed dev info")
log.info("User-facing progress")
log.warning("Recoverable issue")
log.error("Unrecoverable failure")
```

UI log panel: subscribe loguru sink → append to QTextEdit.

### Selectors

- All Grok selectors trong `engines/grok/selectors.py`
- Use `^=` prefix matching
- Document source (snapshot file) trong comments

### Testing

Manual testing tiers:
- **Tier 1**: 1 scene smoke test
- **Tier 2**: 6 scenes voice_test (file đã có)
- **Tier 3**: All visual_types coverage
- **Tier 4**: Error injection (network down, Grok overload)

---

## Appendix A — Build order cho Claude Code

Khi Claude Code build app, thứ tự đề xuất:

```
1. core/schema.py + core/project.py     ← Foundation
2. engines/base.py                      ← Protocol
3. engines/grok/* (selectors, browser, actions, flows, runner)
4. workers/batch_image.py + single_image.py
5. ui/main_window.py + scene_list.py + scene_row.py + connection_panel.py
6. ui/dialogs/preview_image.py + prompt_editor.py
7. runtime/estimator.py
8. workers/batch_video.py + single_video.py
9. render/ken_burns.py
10. slideshow/ + render/slideshow.py wrap
11. workers/slideshow_worker.py + ken_burns_worker.py
12. ── SPRINT 1 DONE ──
13. voice/voice_split.py
14. workers/voice_worker.py
15. render/subtitle.py
16. ── SPRINT 2 DONE ──
17. render/composite.py + assemble.py
18. bgm/picker.py + mixer.py
19. workers/final_video.py
20. ── SPRINT 3 DONE ──
```

## Appendix B — Files đã có (input cho Claude Code)

| File | Vai trò |
|---|---|
| `MASTER_grok_automation.md` | Spec Grok automation chi tiết (selectors, actions, flows, quirks) |
| `Slide_show.md` | Spec slideshow |
| `slideshow/` source code | Offline slideshow pipeline |
| `voice/fish_tts.py` | Module 1 voice pipeline (đã có) |
| `examples/scenes_voice_test.json` | Test file 6 scenes 1 batch |
| `examples/scenes_template_simple.json` | Template chuẩn 6 scenes 2 batches |

## Appendix C — Environment setup

```bash
# Python 3.11+
python --version

# uv install
pip install uv

# Project init
cd story_video_maker
uv venv venv
venv\Scripts\activate

# Dependencies (pyproject.toml):
# pyqt6, qasync, patchright, pydantic, loguru,
# fish-audio-sdk, pillow, opencv-python, numpy, plyer

uv pip install -e .

# Pre-download (1 time):
# - Brave/Chrome with debug port (launch_brave.bat)
# - Fish Audio API key (FISH_API_KEY env)
# - ffmpeg in PATH
# - Claude Code CLI installed + logged in
```

---

## End of Spec

**Next**: Claude Code đọc file này + MASTER_grok_automation.md + Slide_show.md để bắt đầu Sprint 1.

**Maintenance**: Update file này khi:
- Thêm visual_type mới → mục 8.1
- Thêm warning code → mục 14.1
- Schema thay đổi → tăng version + migration script
- Selector Grok đổi → file `engines/grok/selectors.py` (không phải file này)
