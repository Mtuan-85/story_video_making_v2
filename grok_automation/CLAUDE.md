# Grok Automation — Project Context


## Communication Language

ALWAYS reply to the user in Vietnamese, even when reading English source code 
or documentation. Code comments, variable names, log messages, and commit 
messages remain in English. UI strings (PyQt labels, error messages shown to 
user) should be in Vietnamese.
> **For:** Claude Code sessions working on this project
> **Owner:** Tuan 
> **Goal:** PyQt6 desktop app to automate Grok image/video generation via Patchright + CDP

---

## Recent changes

- **2026-04-26 — Fix Batch 3**: Candidates logging + video validation.
  - New `save_candidates_log` action writes
    `output/{project}/candidates/{NNNN}/` containing `strip.png`,
    `0.png..N.png` (per-listitem element screenshots, ready ones only),
    `prompt.txt`, `meta.json`.
  - `pick_image` always writes `pick.json`
    (`{choice, mode, reason, timestamp}`) to the same folder.
    `mode` is `auto`, `claude_fallback` (stub), or `unknown`.
  - `text_to_image` + `image_to_image` flows: `save_candidates_log` step
    inserted between `submit_and_wait_ready` and `pick_image`. Video
    flows untouched (1 result, no grid to log).
  - `validate_before_start` no longer rejects Video + Claude pick —
    video flows don't call `pick_image`, so the UI value is harmless.
  - New `examples/prompts_video.json` demonstrating image→video chain.

## Workflow: Chain image → video

1. Generate images first:
   - Type=Image, project=`lion_series`
   - Load `prompts_simple.json`
   - Output: `output/lion_series/lion_series_pic1.jpg ... pic3.jpg`

2. Generate videos using those images:
   - Type=Video, project=`lion_videos`
   - Ref folder = `output/lion_series/` (point to image output folder)
   - Load `prompts_video.json` (refs match image filenames)
   - Output: `output/lion_videos/lion_videos_vid1.mp4 ... vid3.mp4`

- **2026-04-26 — CHANGE 2**: UI-driven settings refactor.
  - JSON now contains ONLY prompts (string or `{text, ref}`); all other
    settings come from UI controls (Type, Quality, Aspect, Resolution,
    Duration, Pick mode, Typing speed, Timeout, Project name, Ref folder).
  - New `grok/prompt_loader.py` normalizes input.
  - New `examples/prompts_simple.json` + `prompts_with_refs.json`; old
    t2i/i2i/t2v/i2v JSONs removed.
  - 4 flows in `grok/flows.py`: `text_to_image`, `image_to_image`,
    `text_to_video`, `image_to_video`. Flow auto-selected from
    `(type, has_any_ref)`.
  - Target image count: Quality=4, Speed=8 (hard-coded mapping).
  - QSettings persists UI state across sessions (org="Tuan", app="GrokAutomation").
  - `pick_mode='claude'` is stubbed — falls back to index 0 with warning.
    Real `claude_picker.py` deferred to a separate batch.
  - `ProjectPanel` removed; prompts now load from inside `GenerationPanel`.
  - Typing speeds: Fast=10–25 ms, Human=40–110 ms, Slow=80–200 ms.

- **2026-04-26 — CHANGE 1**: Canvas-based ready detection (hotfix).
  - Old `img.opacity-1` detector was wrong — class appears on low-res
    placeholder while `<canvas>` overlay is still painting, causing
    "canvas intercepts pointer events" on click.
  - New `submit_and_wait_ready` action tracks the new masonry by index
    (count before submit, then `.nth(n)` after) and polls listitems for
    "no canvas child".
  - `click_image` filters to ready (no-canvas) listitems and clicks
    `img.opacity-1` inside; falls back to ready[0] if idx OOR.
  - Runner has `_resolve_var` supporting dotted keys
    (`ready_result.masonry_index`).

---

## What this project does

Desktop app that connects to an existing Chrome browser (via CDP debug port 9222) to automate batch generation on `grok.com/imagine`. User provides a JSON list of prompts; app drives Grok UI to generate images/videos, optionally uses Claude Code CLI to pick the best variant out of 4, and downloads results with a custom naming scheme.

**4 generation modes:**
- Text-to-image (with optional reference image)
- Image-to-image
- Text-to-video
- Image-to-video (Make video from existing image)

**3 image pick modes** (only relevant for image generation, since Grok returns 4 candidates):
- `auto` — always pick first image (free, fast, dumb)
- `claude` — call Claude Code CLI subprocess, let Claude vision pick best (free with Pro/Max sub, smart, ~30-60s/pick)
- `manual` — pause pipeline, user picks via local dashboard HTML (deferred, may add later)

---

## Tech stack

| Component | Choice | Why |
|---|---|---|
| UI | PyQt6 | Owner has experience, mature |
| Browser automation | Patchright (async) | Owner already used in AutoBot, undetected mode |
| Async ↔ Qt bridge | qasync | Required for asyncio + Qt event loop |
| Config validation | pydantic v2 | Type-safe JSON loading |
| Logging | loguru | Better than stdlib logging |
| Package manager | uv | Owner's preferred (fast, hard-link cache) |
| Python | 3.11 or 3.12 | Patchright + PyQt6 compat |

**NOT used:** Anthropic SDK / API key. Vision pick goes through Claude Code CLI subprocess to use Pro/Max subscription quota instead.

---

## Browser setup (one-time, user does manually)

User launches Chrome with debug port via batch file `launch_chrome.bat`:

```bat
@echo off
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="D:\chrome-grok-profile" ^
  --no-first-run ^
  --no-default-browser-check ^
  https://grok.com/imagine
```

User logs in to Grok manually first time. Profile persists session. App connects to `http://localhost:9222` via Patchright `connect_over_cdp`.

**Critical:** Do NOT spawn Chrome from Python. Always connect to existing browser.

---

## Folder structure

```
grok_automation/
├── main.py                       # PyQt6 entry point
├── pyproject.toml                # uv project config
├── README.md                     # User-facing docs
├── CLAUDE.md                     # This file
├── launch_chrome.bat             # One-click Chrome launcher
├── .env.example                  # No API keys needed, template only
│
├── grok/                         # All Grok automation logic
│   ├── __init__.py
│   ├── selectors.py              # Selector mappings (from snapshots)
│   ├── browser.py                # CDP connect + tab list/select
│   ├── actions.py                # Atomic actions (submit_and_wait_ready, click_image, upload_ref_if_present, etc.)
│   ├── runner.py                 # Universal flow executor (reads flows.py)
│   ├── flows.py                  # Declarative flow definitions
│   ├── prompt_loader.py          # Load + normalize prompts JSON
│   ├── claude_picker.py          # (TODO) Claude Code CLI subprocess wrapper
│   └── error_detector.py         # (planned) Rate limit + policy fail detection
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py            # MainWindow with all panels
│   └── panels.py                 # All panel widgets (connection, project, generation, run, log)
│
├── workers/
│   ├── __init__.py
│   └── automation_worker.py      # QThread bridge with asyncio (qasync)
│
├── examples/
│   ├── prompts_simple.json       # Plain string prompts only
│   └── prompts_with_refs.json    # Mixed: strings + {text, ref} objects
│
└── output/                       # Auto-created at runtime
    └── {project_name}/
        ├── candidates/{counter:04d}/    # Debug only — strip.png + prompt.txt
        ├── {project}_pic1.jpg           # Renamed downloads
        ├── {project}_pic2.jpg
        └── {project}_vid1.mp4
```

---

## Selector mappings (verified from inspector snapshots)

Source: 5 snapshot JSON files captured by owner using DOM Inspector extension on `grok.com/imagine` and `grok.com/imagine/post/{uuid}`.

### Trang `/imagine` (input page)

| Element | Selector | Notes |
|---|---|---|
| Prompt input | `[contenteditable="true"]` | TipTap editor, `<p>` with class `is-empty is-editor-empty` when empty |
| Submit button | `button[aria-label^="Submit"]` | Or press Enter on input |
| Upload button | `button[aria-label^="Upload"]` | Triggers OS file dialog |
| Mode Image | `button[aria-label^="Image"][role="radio"]` | Inside `div[aria-label="Generation mode"]` |
| Mode Video | `button[aria-label^="Video"][role="radio"]` | Same group |
| Speed/Quality | `button[role="radio"]` + filter text "Speed" or "Quality" |
| Aspect Ratio button | `button[aria-label^="Aspect Ratio"]` | Trigger to open dropdown menu |
| Aspect option | `div[role="menuitem"]` + filter text "16:9", "1:1", etc. | Menu items have `\nWidescreen` etc. as suffix |

### Video-specific (only visible when mode=Video)

| Element | Selector |
|---|---|
| Resolution group | `div[aria-label="Video resolution"]` (contains 480p/720p radios) |
| Duration group | `div[aria-label="Video duration"]` (contains 6s/10s radios) |

### Image generation state (CRITICAL)

| State | Detector |
|---|---|
| Generating (blur) | `[role="listitem"] canvas` exists |
| Ready | `[role="listitem"]` has NO `<canvas>` child |
| Masonry section | `#imagine-masonry-section-{N}` where N=0,1,2... incrementing |

**IMPORTANT:** Do NOT use `img.opacity-1` to detect ready state. That class
appears as soon as the low-res placeholder loads, while a `<canvas>` overlay
is still painting on top. The canvas intercepts pointer events, so clicks
fail with "canvas intercepts pointer events". Ready = listitem has no
`<canvas>` child.

**Wait pattern (correct):**
```python
listitems = new_masonry.locator('[role="listitem"]')
total = await listitems.count()
ready = sum(
    1 for i in range(total)
    if await listitems.nth(i).locator('canvas').count() == 0
)
```

Track the masonry by **index** (`initial_sections` count taken before submit,
then `.nth(initial_sections)` after a new section appears). Using `.last`
races when multiple sections exist.

### Trang `/imagine/post/{uuid}` (result page)

| Element | Selector |
|---|---|
| Download | `button[aria-label^="Download"]` |
| Redo image | `button[aria-label^="Redo image"]` |
| Make video | `button[aria-label^="Make video"]` |
| Play | `button[aria-label^="Play"]` (also has text "More") |
| Back | `div[aria-label^="Back"]` (note: `<div>`, not `<button>`) |

### Video generation progress (text-based detector)

Overlay element appears with text like:
- `"Generating\n5%\nCancel Video"` — at start
- `"Generating\n49%\nCancel Video"` — mid-progress
- Disappears when done

```python
async def video_done():
    overlays = page.locator('div').filter(has_text=re.compile(r'^Generating\s+\d+%'))
    return await overlays.count() == 0
```

---

## Flow design — declarative pattern

**Don't write 1 file per flow.** Use one universal `runner.py` that executes a list of action dicts from `flows.py`.

Example flow definition:

```python
FLOWS = {
    "text_to_image_claude_pick": {
        "name": "Text-to-Image with Claude pick",
        "loop_per_prompt": True,
        "steps": [
            {"action": "ensure_at", "url": "/imagine"},
            {"action": "set_mode", "value": "image"},
            {"action": "set_quality", "value": "quality"},
            {"action": "set_aspect", "from_config": "aspect"},
            {"action": "verify_input_empty"},
            {"action": "fill_prompt", "from_prompt": "text"},
            {"action": "human_pause", "min_ms": 500, "max_ms": 1200},
            {"action": "click_submit"},
            {"action": "wait_image_ready"},
            {"action": "claude_pick_best", "save_to": "best_idx"},
            {"action": "click_image", "from_var": "best_idx"},
            {"action": "wait_url_match", "pattern": "/post/"},
            {"action": "download", "naming": "{project}_pic{counter}"},
            {"action": "click_back"},
            {"action": "wait_url_match", "pattern": "/imagine"},
        ],
    },
    # ... more flows
}
```

`runner.py` resolves params:
- `from_prompt: "text"` → grabs `state["current_prompt"]["text"]`
- `from_config: "aspect"` → grabs `config["aspect"]`
- `from_var: "best_idx"` → grabs `state["vars"]["best_idx"]`
- `naming: "{project}_pic{counter}"` → format-string with config + state

**Adding a new flow** = adding a dict in `flows.py`. Don't create new files.

---

## Human-like behavior

Patchright already simulates real browser. Add small touches:

```python
async def human_type(page, selector: str, text: str):
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.3, 0.6))
    await page.type(selector, text, delay=random.randint(40, 110))
    # 5% chance of "thinking pause"
    if random.random() < 0.05:
        await asyncio.sleep(random.uniform(0.2, 0.6))

async def human_click(locator):
    await locator.scroll_into_view_if_needed()
    await asyncio.sleep(random.uniform(0.2, 0.5))
    await locator.hover()
    await asyncio.sleep(random.uniform(0.1, 0.3))
    await locator.click()

async def human_pause(min_ms=800, max_ms=2500):
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)
```

---

## Claude Code CLI integration (for vision pick)

**Pattern from owner's slideshow_v4 project (proven in production).**

```python
import subprocess, os, json
from pathlib import Path

def pick_best_image(strip_png: Path, prompt_text: str) -> int | None:
    instruction = f"""Tôi vừa generate 4 ảnh trên Grok với prompt:

PROMPT: "{prompt_text}"

Ảnh ở: {strip_png.absolute()}
Đây là strip ngang chứa 4 ảnh, đánh số từ TRÁI sang PHẢI: #0, #1, #2, #3.

Đọc ảnh (dùng Read tool), so sánh với prompt, pick ảnh sát nhất.

Tiêu chí:
1. Đúng nội dung prompt
2. Bố cục đẹp
3. Không có artifact (tay thừa, mặt méo, text lỗi)

OUTPUT (JSON only):
{{"choice": 2, "reason": "ngắn gọn"}}
"""
    
    # CRITICAL: clear API key to force using Pro/Max subscription
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    
    r = subprocess.run(
        ["claude", "-p", instruction],
        capture_output=True, text=True, timeout=120,
        env=env, encoding="utf-8"
    )
    
    if r.returncode != 0:
        return None
    
    # Parse JSON, strip markdown if present
    output = r.stdout.strip()
    if output.startswith("```"):
        output = "\n".join(output.split("\n")[1:-1])
    
    try:
        data = json.loads(output)
        choice = int(data.get("choice", 0))
        if 0 <= choice <= 3:
            return choice
    except:
        # Fallback: extract first digit
        for c in output:
            if c.isdigit():
                n = int(c)
                if 0 <= n <= 3:
                    return n
    return None
```

**Always fallback to index 0** if Claude returns None — pipeline must not crash.

---

## Image strip capture (for Claude pick)

Use Patchright element screenshot — auto-handles viewport, scroll, scaling:

```python
masonry = page.locator('[id^="imagine-masonry-section-"]').last
await masonry.scroll_into_view_if_needed()
await asyncio.sleep(0.5)
await masonry.screenshot(path=str(strip_path))
```

This produces 1 horizontal strip with 4 images. No PIL grid composition needed.

---

## Download rename strategy

Patchright handles download events natively:

```python
async with page.expect_download() as dl_info:
    await page.locator('button[aria-label^="Download"]').click()
download = await dl_info.value

ext = download.suggested_filename.split('.')[-1]  # jpg or mp4
target = output_dir / f"{project}/{project}_{prefix}{counter}.{ext}"
target.parent.mkdir(parents=True, exist_ok=True)
await download.save_as(str(target))
```

`prefix` = `"pic"` for image, `"vid"` for video.

---

## Error detection

Two main failure modes:

**Rate limit**: Toast `[data-sonner-toast]` with text matching `/rate limit|too many|quota|slow down/i`.
**Policy fail**: Toast with text matching `/violat|policy|inappropriate|not allowed|blocked/i`.

```python
async def detect_error(page):
    toasts = page.locator('[data-sonner-toast]')
    n = await toasts.count()
    for i in range(n):
        text = (await toasts.nth(i).text_content() or "").lower()
        if any(k in text for k in ["rate limit", "too many", "quota"]):
            return {"type": "rate_limit", "msg": text}
        if any(k in text for k in ["violat", "policy", "inappropriate", "blocked"]):
            return {"type": "policy_fail", "msg": text}
    return None
```

**Strategy:**
- `rate_limit` → wait + retry (backoff: 60s, 180s, 600s, max 3 attempts), then pause session
- `policy_fail` → log, skip prompt, continue to next
- `timeout` (60s no new masonry slot) → retry once, then skip

---

## Implementation phases

**Phase 1 — Skeleton + Connection** (start here)
- Project structure (uv init)
- PyQt6 MainWindow shell
- BrowserManager: CDP connect, list tabs, dropdown to pick
- ConnectionPanel widget only
- Verify: app connects to Chrome, lists tabs correctly

**Phase 2 — Core text-to-image flow**
- selectors.py with all mappings
- actions.py atomic actions (no Claude pick yet — use auto/index 0)
- runner.py with declarative flow execution
- flows.py with `text_to_image_auto` flow
- Test: load 3 prompts, gen 3 images, files saved with correct naming

**Phase 3 — Claude pick mode**
- claude_picker.py CLI subprocess wrapper
- New action: `claude_pick_best` — capture strip, call Claude, return index
- New flow: `text_to_image_claude_pick`
- Test: Claude picks correctly, fallback works when CLI fails

**Phase 4 — Other modes**
- `image_to_image` flow (with upload)
- `text_to_video` flow (set resolution/duration, wait video overlay)
- `image_to_video` flow (Make video from existing)

**Phase 5 — Error handling + polish**
- error_detector.py with rate limit / policy detection
- Retry/skip logic in runner
- Pause/Stop buttons (graceful)
- Log panel showing progress + errors

---

## Coding conventions

- **Language**: Vietnamese for user-facing strings (UI labels, log messages, errors), English for code/comments/docstrings.
- **Async**: All Patchright calls async. Use `qasync` to integrate with Qt event loop.
- **Errors**: Log with loguru, never crash the UI. Return `{"ok": False, "reason": "..."}` from action functions.
- **State**: All state in `runner.state` dict (counter, vars, current_prompt). No globals.
- **Selectors**: All selectors in `grok/selectors.py`. Don't hardcode in actions.
- **No browser spawn**: Always connect to existing Chrome via CDP.
- **Don't use Anthropic API**: Use Claude Code CLI subprocess only.

---

## What NOT to do

- ❌ Don't spawn new Chrome instance
- ❌ Don't use Anthropic API key (subscription quota only)
- ❌ Don't write 1 Python file per flow — use declarative flows.py
- ❌ Don't compose image grids with PIL — use element screenshot
- ❌ Don't use selenium / playwright sync API — async only
- ❌ Don't crash UI on automation errors — always graceful degrade
- ❌ Don't hardcode coordinates / pixel positions — use selectors
- ❌ Don't trust 1st snapshot of `aria-label` text — always use `^=` prefix matching for resilience
