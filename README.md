# Story Video Maker

Desktop PyQt6 app tự động hóa pipeline tạo video story từ `scenes.json` → `final.mp4`:

- **Gen ảnh** qua Grok Imagine bằng worker process riêng (Brave + CDP + Patchright nằm ngoài GUI)
- **Gen video Grok** đang deferred tới worker process phase sau
- **Animation** offline cho slideshow (ffmpeg + rembg + Claude director)
- **Voice-first alignment** với Whisper + Claude Code CLI (user cung cấp file voice, app align scene timing)
- **Render** ghép visual + voice + subtitle + BGM + fade transitions

## Stack

- Python 3.11+ · PyQt6 + qasync · QProcess workers · Patchright (Playwright fork) · OpenAI Whisper · Claude Code CLI · FFmpeg · uv

## Cấu trúc

```
core/          # Schema, project state, paths, voice_mapping, config loader
engines/       # Provider/browser automation implementations
  grok/        # Selectors, atomic actions, declarative flows, FlowRunner, engine adapters
render/        # FFmpeg composition + assembly + transitions
runtime/       # Estimator với rolling history (time prediction per action)
slideshow/     # External slideshow pipeline (preprocess + Claude director + ffmpeg overlay)
ui/            # MainWindow, ConnectionPanel, SceneList, dialogs (preview + prompt + voice)
voice/         # Whisper transcription + Claude alignment + subtitle builder + Fish TTS (legacy CLI)
workers/       # QProcess task contract/launcher + legacy/offline workers
test_run/      # Working example project (scenes.json + state)
```

### File roles (key modules)

**core/**
- `schema.py` — Pydantic v2 schema cho `scenes.json` (`Scene`, `Meta`, `VisualType` Literal); generation config lives under `meta`
- `project.py` — `Project.load()` đọc scenes.json + state.json, tracking per-scene status, atomic backup
- `paths.py` — `ProjectPaths`: `image_path(N)`, `video_path(N)`, `voice_dir`, `renders_dir`, etc.
- `voice_mapping.py` — Schema `VoiceMapping` (voice_files + per-scene voice_in/out + subtitle_phrases)
- `config.py` — `load_config()` + `wait_brave_ready()` poll CDP port

**engines/grok/**
- `browser.py` — `GrokConnection`: connect_over_cdp + tab select + `reconnect_cdp()` + `kill_and_relaunch_brave()`
- `selectors.py` — DOM selectors (prefix-match `aria-label`)
- `actions.py` — atomic async actions (ensure_at, set_mode, fill_prompt with per-char human typing, submit_and_wait_ready, upload_ref_if_present multi-file, click_image, download_to, wait_image_ready, wait_video_ready, …)
- `flows.py` — 4 declarative flows: text_to_image / image_to_image / text_to_video / image_to_video
- `runner.py` — `FlowRunner`: dispatch step dict → action call, supports stop event + list-vs-scalar ref dispatch
- `engine.py` — `GrokImageEngine`, `GrokVideoEngine` (masonry + Claude pick)
- `image_ref_engine.py` — `GrokImageRefEngine`: linear flow for image-with-refs (upload → set_aspect → prompt → submit → 30s fixed wait → poll overlay+download → save). 11 stop checkpoints.
- `claude_picker.py` — Claude CLI vision-pick best image candidate
- `cdp_worker.py` — worker-local CDP attach, stale Patchright/Playwright `node.exe` cleanup for the configured port, tab reuse/open helper
- `image_worker_flow.py` — Grok batch/single image flow used by `workers.generate_worker`

**render/**
- `slideshow.py` — Async wrapper + sys.path injection cho `slideshow/` external pipeline
- `composite.py` — `composite_scene()`: visual + voice slice + subtitle drawtext + fade-in/out 0.25s mỗi side
- `subtitle_filter.py` — Build drawtext chain per phrase (yellow + black border, scene-relative timestamps)
- `bgm_mixer.py` — `pick_bgm_files` + `build_bgm_filter` (aloop + atrim + volume -15dB + afade)
- `assemble.py` — Hard-cut concat via `filter_complex concat=` + optional BGM mix

**workers/**
- `task_contract.py` — typed task JSON, worker events, exit codes; default CDP URL `http://127.0.0.1:9222`
- `process_launcher.py` — PyQt `QProcess` wrapper; parses `TASK START` / `EVENT` / `TASK DONE` / `TASK FAILED`
- `generate_worker.py` — CLI entrypoint for batch/single image tasks; Grok image implemented, ChatGPT/Gemini deferred

Legacy/offline workers:
- `_async_thread.py` — `AsyncTaskWorker` base (start, request_stop, run_with_stop)
- `_retry.py` — legacy in-process retry helper for old workers; not used by the new QProcess image path
- `batch_image.py` / `single_image.py` — legacy in-process image workers kept temporarily; GUI image path now uses `GenerateProcess`
- `batch_video.py` / `single_video.py` — legacy Grok video workers; GUI Grok video is deferred until process-worker phase
- `slideshow_worker.py` — Single-scene slideshow render
- `voice_align_worker.py` — Whisper + Claude align (blocking, wrapped trong `asyncio.to_thread`)
- `render_worker.py` — Composite all scenes → assemble final.mp4

**ui/**
- `main_window.py` — Wires provider config + project + scene list + QProcess image generation + offline workers; Stop All button + worker registry
- `connection_panel.py` — Provider/model/CDP URL health panel; does not own Patchright, browser, page, or tab state
- `refs_panel.py` — `RefImagesPanel`: multi-ref upload (max 5) for image-with-refs flow, persisted to state.json
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
Mỗi scene declare: `id`, `visual_type` (`Image` | `Video` | `slideshow`), `imagePrompt`, `videoPrompt` (optional), `story_en`/`story_vi`, `duration`. `image_grok` / `video_grok` vẫn được nhận khi load file cũ nhưng sẽ được normalize về `Image` / `Video` khi app save lại.

### 2. Mở app + chuẩn bị Brave/CDP
```bash
launch_brave.bat       # mở Brave với CDP port 9222 + Grok logged in
python main.py         # mở app
```
Trong app, panel Provider dùng mặc định `http://127.0.0.1:9222`. Nút **Check CDP** chỉ kiểm tra health; GUI không connect Patchright và không chọn tab. Worker image sẽ tự attach CDP, mở/reuse Grok tab, rồi chạy flow.

### 3. Load project
📂 **Mở scenes.json** → app đọc + tạo `state.json` + render scene rows.

### 4. Gen ảnh
Tick scenes → ➕ **Batch ảnh** → confirm estimate → GUI tạo `GenerateTask` và chạy `workers.generate_worker` qua `GenerateProcess`.

Two engines depending on the **Reference Images panel**:
- ☐ Use refs OFF → `GrokImageEngine` (4-candidate masonry + Claude pick)
- ☑ Use refs ON (1-5 ref images uploaded) → `GrokImageRefEngine` (linear single-result flow). Aspect auto-resets to "Original" on Grok after upload — engine re-applies project aspect.

Per scene:
- Worker emits `scene_started`, `scene_done`, `scene_failed`.
- GUI owns state updates and thumbnails from those events.
- Output downloads to `sources/picN.jpg`.
- Stop kills the image `QProcess`; browser process is not killed by the GUI.
- Provider/model is project-level for now: Grok / `grok-auto`.
- ChatGPT/Gemini providers are schema/UI-ready concepts only; implementation deferred.

### 5. Gen animation (ai cần)
Slideshow is an offline render/tool flow, not a Grok/ChatGPT/Gemini provider flow. Single-scene slideshow remains available from the preview dialog.

Batch Grok video and single Grok video are deferred until the video process-worker phase. The old in-process Patchright video path is not used by the GUI after the image worker refactor.

Current status:
| visual_type | Path | Output |
|---|---|---|
| `Image` | skip (still image) | – |
| `Video` | deferred | – |
| `slideshow` | `SlideshowWorker` / `render_slideshow` (offline, single scene) | `sources/vidN.mp4` |

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

## CDP / Worker behavior

- GUI does not import `patchright` and does not own `GrokConnection`, `Browser`, `Context`, or `Page`.
- Each image batch/single regen is one worker process and one provider flow.
- Worker connects to `http://127.0.0.1:9222` by default.
- CDP stale `node.exe` cleanup is opt-in via `STORY_VIDEO_KILL_STALE_CDP=1`; by default the worker does not kill browser or driver processes.
- GUI parses worker stdout markers and updates `state.json` itself.

Reload remains GUI-owned: app reload scans `sources/` and reconciles state after crash/restart.

## License

Private project. Not for redistribution.
