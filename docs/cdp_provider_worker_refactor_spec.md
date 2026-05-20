# CDP + Provider Worker Refactor Spec

**Ngày viết:** 2026-05-20  
**Trạng thái:** Implemented for schema + Grok image vertical slice; Grok video/ChatGPT/Gemini deferred  
**Mục tiêu:** Tách GUI khỏi Patchright/CDP, chuẩn hóa batch/single generation thành worker process, và mở đường cho chọn provider/model Grok, ChatGPT, Gemini mà không phá cấu trúc app.

---

## 0. Quyết định đã chốt

1. **GUI không own Patchright/CDP.**
   - `MainWindow` và các widget không giữ `GrokConnection`, `Page`, `Browser`, `GrokImageEngine`, `GrokVideoEngine`.
   - GUI chỉ load project, chọn provider/model, tạo task request, spawn worker process, đọc stdout markers, update UI.

2. **Batch = 1 worker process = 1 provider flow.**
   - Batch image/video không cần `1 scene = 1 process`.
   - Một batch process connect CDP một lần, chọn/mở đúng tab provider một lần, rồi chạy tuần tự các scene trong flow đó.
   - Lý do: Grok đã test ổn với batch process/flow; ChatGPT/Gemini cũng tự nhiên hơn nếu một batch chạy trong một chat/session liên tục.

3. **Single re-gen = 1 worker process = 1 single flow.**
   - Re-gen lẻ mở hoặc reset một flow riêng, chạy một scene rồi exit.
   - Sau này nếu muốn single dùng chung exact batch implementation, chỉ đổi worker routing, GUI contract không đổi.

4. **Provider/model pick là input của task.**
   - GUI chọn provider/model ở project-level.
   - Batch/re-gen đọc lựa chọn đó và ghi vào task JSON.
   - Worker router dispatch theo `provider`.
   - Per-scene provider/model selection để sau. Workflow hiện tại ưu tiên chạy một batch hoặc full project trên một model; nếu hết limit, user reload/refresh rồi chạy tiếp bằng model thứ hai.

5. **Schema project chuyển sang meta mới.**
   - Root `version` không còn là schema version của app.
   - Nếu file có root `version`, khi save lại chuyển vào `meta.version`.
   - `settings` bị loại bỏ; các generation defaults đặt trong `meta`.
   - `visual_type` là app-level, không provider-specific: `Image`, `Video`, `slideshow`.
   - Legacy aliases `image_grok` / `video_grok` được nhận khi load và được save lại thành `Image` / `Video`.

---

## 1. Project JSON schema mới

### 1.1 Shape chuẩn

```json
{
  "meta": {
    "version": "1.1",
    "project_id": "Naomi_01",
    "title": "Raising Children Who Cooperate Willingly",
    "aspect_ratio": "16:9",
    "language": "en",
    "baseStyle": "Cozy flat cartoon illustration...",
    "baseNegative": "photorealistic, 3D render...",
    "image_quality": "quality",
    "video_resolution": "720p",
    "video_duration": "10s",
    "source_citations": "Processed from the attached source document...",
    "topic": null
  },
  "character": {
    "Naomi": "A 38-year-old Japanese woman...",
    "Kimiko": "An elderly Japanese woman..."
  },
  "scenes": [
    {
      "id": "1",
      "visual_type": "Image",
      "effect": "zoom_in",
      "story_en": "...",
      "imagePrompt": "...",
      "videoPrompt": null,
      "duration": 8
    }
  ]
}
```

### 1.2 Field policy

| Field | Policy |
|---|---|
| `meta.version` | Chain/project version từ app tạo JSON. App giữ lại, không dùng làm schema gate cứng. |
| root `version` | Legacy/input-only. Nếu gặp thì migrate vào `meta.version`, không save lại root `version`. |
| `settings` | Deprecated. Không dùng trong schema mới. |
| `meta.baseStyle` | Style chung để build prompt image/video. |
| `meta.baseNegative` | Negative prompt chung. |
| `meta.image_quality` | Grok image preset, default `"quality"`. |
| `meta.video_resolution` | Grok video preset, default `"720p"`. |
| `meta.video_duration` | Grok video duration, default `"10s"`. |
| `meta.topic` | Optional. Nếu thiếu, code fallback sang `meta.title`. |
| `character` | Root-level `dict[str, str]`. Dùng để append prompt/context sau này; phase đầu chỉ load/save giữ nguyên. |
| `scene.visual_type` | Canonical values: `Image`, `Video`, `slideshow`. Provider is selected at task/project level, not embedded in scene data. |

### 1.3 Code impact

Các chỗ đang đọc `project.scenes_json.settings.*` phải chuyển sang `project.scenes_json.meta.*`:

- `workers/batch_image.py`
- `workers/batch_video.py`
- các worker/process mới khi build task settings
- docs/README/SPEC sau khi implement

---

## 2. Current architecture problem

Hiện tại:

```text
GUI PyQt/qasync process
  -> imports engines.grok
  -> owns GrokConnection
  -> owns Patchright Page/Browser through GrokConnection
  -> creates GrokImageEngine/GrokVideoEngine
  -> runs async workers on same long-lived GUI process
```

Vấn đề theo skill `playwright-cdp-resilient`:

- GUI import/own Patchright làm CDP driver state sống quá lâu.
- qasync + long-lived Patchright dễ hang silent ở retry/run thứ N.
- Retry hiện tại có thể kill Brave bằng process name, rủi ro giết browser cá nhân.
- Thêm ChatGPT/Gemini vào kiến trúc hiện tại sẽ làm GUI càng biết quá nhiều provider-specific details.

---

## 3. Target architecture

```text
GUI PyQt process
  - no Patchright import
  - no provider DOM knowledge
  - builds task JSON
  - QProcess.start(worker CLI)
  - parses EVENT/TASK markers
  - updates project state + UI

Worker process
  - imports Patchright
  - connects CDP
  - opens/reuses provider tab
  - runs one batch flow or one single flow
  - downloads outputs
  - emits structured stdout markers
  - exits

Browser Brave automation profile
  - user opens once
  - login/session persists
  - workers attach over CDP
```

### 3.1 Process granularity

| User action | Worker process | Provider flow |
|---|---|---|
| Batch image | 1 process for selected scenes | 1 batch flow, same provider tab/chat/session |
| Batch video | 1 process for selected scenes | 1 batch flow, same provider tab/chat/session |
| Re-gen image | 1 process for one scene | 1 clean single flow |
| Re-gen video | 1 process for one scene | 1 clean single flow |

### 3.2 Browser/tab policy

- User opens Brave automation profile manually or via launcher.
- Worker connects to `http://127.0.0.1:<port>`.
- Stale CDP `node.exe` cleanup is opt-in via `STORY_VIDEO_KILL_STALE_CDP=1`.
- Worker does **not** kill browser on normal provider flow failure.
- Browser kill/relaunch only allowed when CDP/browser is unreachable and must be scoped by automation `--user-data-dir`, never by `/IM brave.exe`.
- Batch flow should not close/open tabs repeatedly.
- Worker should get or open provider tab:
  - Grok: base URL `https://grok.com/imagine`
  - ChatGPT: later
  - Gemini: later
- Single flow may open new chat/tab or reset base URL for clean context.

---

## 4. Provider/model contract

### 4.1 Provider identifiers

Phase đầu:

```text
provider = "grok"
model = "grok-auto"
```

Reserved:

```text
provider = "chatgpt"
provider = "gemini"
```

### 4.2 Task request JSON

```json
{
  "task_id": "20260520_110000_batch_image_ab12",
  "project_file": "D:/Projects/story_video_making_v2/project/Naomi_01.json",
  "project_root": "D:/Projects/story_video_making_v2/project",
  "task_type": "batch_image",
  "provider": "grok",
  "model": "grok-auto",
  "cdp": {
    "url": "http://127.0.0.1:9222",
    "profile_marker": "brave-grok-profile",
    "base_url": "https://grok.com/imagine"
  },
  "scene_ids": ["1", "2", "3"],
  "options": {
    "pick_mode": "auto",
    "fast_mode": false,
    "use_refs_for_image": false,
    "image_refs": []
  }
}
```

### 4.3 Task types

```text
batch_image
batch_video
single_image
single_video
```

### 4.4 Worker router

```text
worker_generate.py
  -> load task JSON
  -> if provider == "grok": run grok worker flow
  -> if provider == "chatgpt": fail unsupported for now
  -> if provider == "gemini": fail unsupported for now
```

Provider-specific code lives under:

```text
engines/grok/
engines/chatgpt/    # future
engines/gemini/     # future
```

GUI does not import provider flow modules.

---

## 5. Worker stdout and exit code API

### 5.1 Structured stdout markers

Worker stdout is human-readable, but GUI only parses these markers:

```text
TASK START {"task_id":"...","task_type":"batch_image","provider":"grok"}
EVENT {"type":"scene_started","scene_id":"1"}
EVENT {"type":"scene_done","scene_id":"1","asset":"image","path":"sources/pic1.jpg","duration_sec":42.1}
EVENT {"type":"scene_failed","scene_id":"2","asset":"image","reason":"..."}
TASK DONE {"success":2,"total":3,"duration_sec":123.4}
TASK FAILED {"reason":"...","code":1}
```

### 5.2 Exit codes

| Code | Meaning | GUI action |
|---|---|---|
| 0 | Success | Mark task done |
| 1 | Provider/browser flow failed | Show Retry/Cancel |
| 2 | Prerequisite missing | Stop, show missing input |
| 3 | Killed by user | Mark stopped |
| 4 | Provider succeeded but parse/download failed | Show raw/log path |
| 5 | CDP/browser unreachable | Ask user to open Brave/retry |
| 6 | Project lock held | Show locked/running warning |

---

## 6. GUI changes

### 6.1 Connection panel becomes health/model panel

Old role:

```text
Connect CDP -> select tab -> emit Page -> create engine
```

New role:

```text
Show CDP URL
Check browser health via /json/version
Select provider/model
No Patchright connect
No Page object
```

Suggested UI fields:

- Provider: `Grok` now; `ChatGPT`, `Gemini` disabled or hidden until implemented.
- Model: `grok-auto` now.
- CDP URL: `http://127.0.0.1:9222`.
- Button: `Check Browser`.

### 6.2 Batch buttons

`Batch ảnh`:

1. Build task JSON with selected scenes.
2. Spawn worker process.
3. Disable conflicting buttons while process runs.
4. Parse `EVENT` markers to refresh scene rows.
5. Stop button kills QProcess.

`Batch animation` follows same launcher pattern.

### 6.3 Single re-gen

PreviewDialog emits same `gen_image_requested(scene_id, fast_mode)` and `gen_animation_requested(scene_id, fast_mode)`.

MainWindow no longer creates `SingleImageWorker`/`SingleVideoWorker`; it builds `single_image` or `single_video` task and spawns QProcess.

---

## 7. State ownership

Two viable options:

### Option A — GUI owns state writes

Worker downloads files and emits `EVENT scene_done`. GUI updates `Project.state`.

Pros:
- One writer for state.
- Lower ghost-writer risk.

Cons:
- Worker must emit every result accurately.
- If GUI dies while worker succeeds, state may not update.

### Option B — Worker writes state with run_id guard

Worker loads project/state and writes result directly. GUI reloads state after events.

Pros:
- Worker completion persists even if GUI crashes.

Cons:
- Needs project lock/run_id protection.
- More implementation now.

**Decision for first vertical slice:** Option A. Keep state writes in GUI while proving QProcess/provider boundary. Add run_id state writes later if needed.

### 7.1 Decision detail: GUI-owned state is better for reload/resume now

For the current app, GUI-owned state writes are the safer first design:

- The existing `Project` object already owns state reconciliation, atomic writes, scene row refresh, thumbnail regeneration triggers, and reload summaries.
- Reload after app restart remains simple: GUI loads `<stem>_state.json`, then runs `Project.reload()` to reconcile real files in `sources/`.
- Worker process can stay a disposable provider runner: download assets, emit structured `EVENT` output, and exit. It does not need to know all UI/runtime state rules.
- If the GUI crashes while a worker succeeds, the downloaded file still exists in `sources/`; next app run can recover via reload/scan. This is acceptable for the first vertical slice.
- Worker-owned state would require project locks, run_id ghost-writer protection, and conflict handling from day one. That is valuable later, but adds risk before the GUI/CDP boundary is proven.

Therefore:

```text
Phase C/D/E:
  Worker writes files only.
  Worker emits scene_done/scene_failed events.
  GUI updates Project.state and thumbnails.
  Reload remains the recovery path after crash/restart.
```

---

## 8. Reload/source naming interaction

This refactor should not absorb the whole reload patch. Keep separation:

1. Provider worker boundary first.
2. Schema meta update can be done before/with worker boundary because prompt settings depend on it.
3. `image_file`/`video_file` explicit naming and thumbnail invalidation remain a separate patch after worker boundary.

Reason: path naming touches output path decisions in every worker. Once worker task contract exists, output path fields can be added cleanly to task JSON.

---

## 8.1 Slideshow/render flow is not a provider model flow

Slideshow is not part of Grok/ChatGPT/Gemini model generation. It is an offline render/animation tool chain, closer to `render/` than `engines/<provider>/`.

Policy:

- Do not put `slideshow` under provider/model selection.
- Do not route slideshow through `provider = "grok" | "chatgpt" | "gemini"`.
- Keep slideshow as a separate animation/render capability.
- Later, when there are multiple animation skills/tools, add a separate `animation_tool` or `render_tool` selector rather than overloading model provider.

Implication for video workers:

```text
Batch animation
  - `Video` scenes -> provider worker flow
  - slideshow scenes -> offline render worker/tool flow
  - future animation skills -> offline render worker/tool flow
```

This separation keeps "model generation" and "animation/render tooling" independent.

---

## 9. Implementation phases

### Phase A — Schema meta update

Goal:
- Accept new JSON shape.
- Move root `version` to `meta.version` on save.
- Remove dependency on `settings`.

Files likely touched:
- `core/schema.py`
- `workers/batch_image.py`
- `workers/batch_video.py`
- `workers/single_image.py`
- `workers/single_video.py`
- docs after code

Verification:
- Load sample project JSON with `meta.baseStyle`, `character`, no `settings`.
- Existing project with root `version/settings` either loads via compatibility or fails with clear message, based on final implementation decision.

### Phase B — Task contract and QProcess launcher skeleton

Goal:
- Add task JSON builder and process launcher.
- GUI can spawn a no-op worker and parse markers.

Files likely added:
- `workers/process_launcher.py`
- `workers/task_contract.py`
- `worker_generate.py` or `workers/worker_generate.py`

Verification:
- Spawn no-op `batch_image` task.
- GUI log receives `TASK START`, `EVENT`, `TASK DONE`.
- Stop kills QProcess.

### Phase C — Grok batch image + single image vertical slice

Goal:
- Move Grok image Patchright ownership into worker process for both batch image and single image.
- GUI no longer uses `GrokConnection` for image generation.

Batch flow:
1. Worker connects CDP.
2. Worker opens/reuses Grok tab.
3. Worker runs selected scenes sequentially.
4. Worker downloads images.
5. Worker emits per-scene events.
6. GUI updates state + thumbnails.

Single flow:
1. Worker connects CDP.
2. Worker opens/resets a clean Grok tab/flow.
3. Worker runs one scene.
4. Worker downloads image.
5. Worker emits one scene event.
6. GUI updates state + thumbnail.

Verification:
- Batch image 2 scenes succeeds.
- PreviewDialog Gen Image succeeds.
- Fast mode option passes into single image task JSON.
- GUI remains responsive.
- Repeat 5 batches without restarting GUI.

### Phase D — Grok batch video + single video

Goal:
- Port video Grok flow and offline slideshow dispatch as needed.

Decision needed during implementation:
- `Video` routes through provider worker flow.
- `slideshow` stays outside provider/model flow and should be handled as an offline render/tool worker.
- Recommendation: keep the same QProcess launcher infrastructure for process isolation, but use a separate task family such as `render_slideshow`, not `provider=grok`.

### Phase E — Remove GUI CDP ownership

Goal:
- `ui/connection_panel.py` no longer imports `engines.grok`.
- `MainWindow` no longer stores `image_engine/video_engine`.
- Old in-process workers can be deleted or kept temporarily under `legacy`.

Verification:
- `rg "patchright|GrokConnection|GrokImageEngine|GrokVideoEngine" ui workers` shows no GUI imports, except worker process modules.

---

## 10. Acceptance criteria

### Schema

- [x] Project JSON with `meta.version` and no root `version` loads.
- [x] Project JSON with root `version` saves back with `meta.version`, root `version` removed.
- [x] Project JSON with root `character` loads and saves unchanged.
- [x] `settings` is no longer required.
- [x] `image_grok` / `video_grok` load as aliases and save as `Image` / `Video`.

### GUI/CDP boundary

- [x] GUI process imports no `patchright.async_api`.
- [x] GUI process does not instantiate `GrokConnection`.
- [x] Batch image starts a QProcess worker.
- [x] Stop kills the active worker process.
- [x] Worker process exit does not crash GUI.

### Grok batch flow

- [ ] User opens Brave automation profile.
- [ ] Batch image selected scenes run in one worker process/flow.
- [ ] Worker connects CDP using `127.0.0.1`.
- [ ] Worker does not kill Brave on ordinary scene failure.
- [ ] Scene events update UI state and thumbnails.

### Provider extensibility

- [x] Task JSON contains `provider` and `model`.
- [x] Unsupported `chatgpt/gemini` returns clear exit code/message.
- [x] Adding new provider does not require GUI DOM changes.
- [x] Slideshow is not exposed as a provider/model option.

---

## 11. Non-goals for this refactor

- Do not implement ChatGPT/Gemini generation yet.
- Do not rewrite render/voice pipeline.
- Do not solve explicit `image_file`/`video_file` naming in this phase unless needed by task contract.
- Do not build a new app from scratch.
- Do not keep both GUI-owned CDP and worker-owned CDP as long-term architecture.

---

## 12. Open questions before implementation

None for the first implementation plan.

Recommended defaults:

- First implementation includes both `batch_image` and `single_image`.
- Use `127.0.0.1:9222`. Keep port `9222` because port `9223` is reserved for another project on this machine.
