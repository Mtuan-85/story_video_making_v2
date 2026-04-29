# Story Video Maker

Desktop PyQt6 app tự động hóa pipeline tạo video story từ `scenes.json` → `final.mp4`:

- **Gen ảnh/video** qua Grok Imagine (browser automation Brave + CDP + Patchright)
- **Animation** offline cho slideshow / Ken Burns (ffmpeg + rembg + Claude director)
- **Voice-first alignment** với Whisper + Claude Code CLI (user cung cấp file voice, app align scene timing)
- **Render** ghép visual + voice + subtitle + BGM + fade transitions

## Stack

- Python 3.11+ · PyQt6 + qasync · Patchright (Playwright fork) · OpenAI Whisper · Claude Code CLI · FFmpeg · uv

## Cấu trúc

```
core/          # Schema, project state, paths, voice_mapping, config loader
engines/       # Browser automation Grok
  grok/        # Selectors, atomic actions, declarative flows, FlowRunner, engine adapters
render/        # FFmpeg composition + assembly + transitions
runtime/       # Estimator với rolling history (time prediction per action)
slideshow/     # External slideshow pipeline (preprocess + Claude director + ffmpeg overlay)
ui/            # MainWindow, ConnectionPanel, SceneList, dialogs (preview + prompt + voice)
voice/         # Whisper transcription + Claude alignment + subtitle builder + Fish TTS (legacy CLI)
workers/       # Async task workers chạy trên qasync loop chính
test_run/      # Working example project (scenes.json + state)
```

### File roles (key modules)

**core/**
- `schema.py` — Pydantic v2 schema cho `scenes.json` (`Scene`, `Settings`, `Meta`, `VisualType` Literal)
- `project.py` — `Project.load()` đọc scenes.json + state.json, tracking per-scene status, atomic backup
- `paths.py` — `ProjectPaths`: `image_path(N)`, `video_path(N)`, `voice_dir`, `renders_dir`, etc.
- `voice_mapping.py` — Schema `VoiceMapping` (voice_files + per-scene voice_in/out + subtitle_phrases)
- `config.py` — `load_config()` + `wait_brave_ready()` poll CDP port

**engines/grok/**
- `browser.py` — `GrokConnection`: connect_over_cdp + tab select + `reconnect_cdp()` + `kill_and_relaunch_brave()`
- `selectors.py` — DOM selectors (prefix-match `aria-label`)
- `actions.py` — 23 atomic async actions (ensure_at, set_mode, fill_prompt, submit_and_wait_ready, click_image, download_to, wait_video_ready, …)
- `flows.py` — 4 declarative flows: text_to_image / image_to_image / text_to_video / image_to_video
- `runner.py` — `FlowRunner`: dispatch step dict → action call, supports stop event
- `engine.py` — `GrokImageEngine`, `GrokVideoEngine` (high-level adapter implementing Protocols)
- `claude_picker.py` — Claude CLI vision-pick best image candidate

**render/**
- `ken_burns.py` — Zoompan filter (`ZOOM_RANGE_DEFAULT=0.2`, total over duration), `ken_burns_self` + `ken_burns_continuation`
- `slideshow.py` — Async wrapper + sys.path injection cho `slideshow/` external pipeline
- `composite.py` — `composite_scene()`: visual + voice slice + subtitle drawtext + fade-in/out 0.25s mỗi side
- `subtitle_filter.py` — Build drawtext chain per phrase (yellow + black border, scene-relative timestamps)
- `bgm_mixer.py` — `pick_bgm_files` + `build_bgm_filter` (aloop + atrim + volume -15dB + afade)
- `assemble.py` — Hard-cut concat via `filter_complex concat=` + optional BGM mix

**workers/** (subclass `AsyncTaskWorker` → qasync main loop)
- `_async_thread.py` — `AsyncTaskWorker` base (start, request_stop, run_with_stop)
- `_retry.py` — `run_with_retry()`: 3 attempts, kill+relaunch Brave between fails, exhaust → `needs_user_decision`
- `batch_image.py` — `BatchImageWorker`: gen ảnh per selected scene, retry+kill+relaunch
- `batch_video.py` — `BatchVideoWorker`: dispatcher theo `visual_type` (Grok / slideshow / ken_burns offline)
- `single_image.py` / `single_video.py` — Re-gen 1 scene
- `slideshow_worker.py` / `ken_burns_worker.py` — Single-scene slideshow / KB render
- `voice_align_worker.py` — Whisper + Claude align (blocking, wrapped trong `asyncio.to_thread`)
- `render_worker.py` — Composite all scenes → assemble final.mp4

**ui/**
- `main_window.py` — Wires connection + project + scene list + buttons + dialogs + workers
- `connection_panel.py` — CDP URL + connect/disconnect + tab dropdown
- `scene_list.py` + `scene_row.py` — Per-scene row (status icons, regen/edit, batch checkbox)
- `dialogs/` — `preview_image`, `preview_video`, `prompt_editor`, `voice_import`, `voice_align_review`

**voice/**
- `whisper_runner.py` — Wraps `whisper` CLI, returns word-level JSON
- `voice_aligner.py` — Whisper → Claude CLI prompt → parse JSON → `VoiceFile`
- `subtitle_builder.py` — Fallback: group Whisper words into phrases by punctuation
- `fish_tts.py` — Legacy CLI-only TTS tool (Fish Audio); not imported by main app

## Cài đặt

### Prerequisites

- Python 3.11+
- Brave Browser
- FFmpeg in PATH
- Node.js + Claude Code CLI (`claude` available in PATH)
- (optional) VLC for preview

### Install

```bash
uv venv .venv
.venv\Scripts\activate
uv pip install -r requirements.txt
```

### Per-install config

`config.json` (gitignored, app-root) — Brave launch params for kill+relaunch retry:
```json
{
  "brave": {
    "launch_bat": "launch_brave.bat",
    "process_name": "brave.exe",
    "debug_port": 9222
  }
}
```

`launch_brave.bat` — launches Brave with `--remote-debugging-port=9222` against a dedicated profile.

## Flow đầy đủ (input → output)

### 1. Chuẩn bị `scenes.json`
Mỗi scene declare: `id`, `visual_type` (`image_grok` | `video_grok` | `slideshow` | `ken_burns_self` | `ken_burns_cont`), `imagePrompt`, `videoPrompt` (optional), `story_en`/`story_vi`, `duration`. Xem `test_run/scenes.json` mẫu.

### 2. Mở app + kết nối Brave
```bash
launch_brave.bat       # mở Brave với CDP port 9222 + Grok logged in
python main.py         # mở app
```
Click 🔌 **Kết nối** → chọn Grok tab → app sẵn sàng.

### 3. Load project
📂 **Mở scenes.json** → app đọc + tạo `state.json` + render scene rows.

### 4. Gen ảnh
Tick scenes → ➕ **Batch ảnh** → confirm estimate → `BatchImageWorker` chạy:
- Per scene: `GrokImageEngine.gen_image()` → ảnh download về `sources/picN.jpg`
- Fail → `run_with_retry`: kill brave + `launch_brave.bat` + wait CDP + reconnect → retry (max 3)
- Exhaust → popup `[Retry / Skip / Abort]`

### 5. Gen animation (ai cần)
Tick scenes → 🎞 **Batch animation** → `BatchVideoWorker` dispatch theo `visual_type`:
| visual_type | Path | Output |
|---|---|---|
| `image_grok` | skip (still image) | – |
| `video_grok` | Grok I2V (cần Brave + retry) | `sources/vidN.mp4` |
| `slideshow` | `render_slideshow` (offline) | `sources/vidN.mp4` |
| `ken_burns_self` | zoompan filter (offline) | `sources/vidN.mp4` |
| `ken_burns_cont` | extract last frame prev video → zoompan | `sources/vidN.mp4` |

### 6. Import voice + align
🎤 **Import voice** → wizard chọn voice files + assign scene → `VoiceAlignWorker`:
- Whisper transcribe (word-level timestamps)
- Claude CLI maps Whisper words → scene story → tính `voice_in`/`voice_out` + `subtitle_phrases`
- Save `voice_mapping.json` → review dialog cho user chỉnh start/end
- `method="user_override"` ghi nhận khi user save chỉnh tay

### 7. Render final
🎬 **Render final** → `RenderWorker`:
- Per scene: `composite_scene()` → ffmpeg dựng `renders/{id}.mp4` (visual + voice slice + drawtext subtitles + fade-in/out 0.25s)
- `assemble_final()` → hard-cut concat (KHÔNG xfade) + optional BGM mix → `final.mp4`

## Smart retry behavior

Bất kỳ exception nào trong worker (Grok image/video):
1. `kill brave.exe` → `launch_brave.bat` → poll `localhost:9222/json/version` (max 30s) → `reconnect_cdp` + select grok tab → refresh `engine.page`
2. Retry lần kế tiếp
3. Sau 3 fail liên tiếp → emit `scene_needs_user_decision` → MainWindow popup `[Retry / Skip / Abort batch]`

Single-scene re-gen retry silent (không popup) — user tự click re-gen lại nếu cần.

## License

Private project. Not for redistribution.
