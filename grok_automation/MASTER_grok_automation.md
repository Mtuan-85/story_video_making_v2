# Grok Automation — Master Specification

> **Purpose**: Complete specification of grok_automation project. Any AI 
> (Claude, GPT, Gemini, etc.) or developer can read this single document 
> and understand the architecture, logic, and selectors required to 
> rebuild or maintain the project.
>
> **Last updated**: April 2026
> **Owner**: Tuan (Vietnamese developer, BA + Bigdata background)
> **Project status**: Phase 2 — core flows working, video flow being stabilized

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Architecture](#3-architecture)
4. [Browser Setup (CDP)](#4-browser-setup-cdp)
5. [UI Specification](#5-ui-specification)
6. [JSON Input Format](#6-json-input-format)
7. [Selectors Reference](#7-selectors-reference)
8. [DOM State Patterns](#8-dom-state-patterns)
9. [Atomic Actions](#9-atomic-actions)
10. [Flows](#10-flows)
11. [Error Handling](#11-error-handling)
12. [Output Structure](#12-output-structure)
13. [Coding Conventions](#13-coding-conventions)
14. [Testing Strategy](#14-testing-strategy)
15. [Known Issues & Quirks](#15-known-issues--quirks)

---

## 1. Project Overview

### What it does

Desktop application (PyQt6) that automates batch image and video generation 
on `grok.com/imagine`. The app connects to an existing Brave/Chrome browser 
via CDP (Chrome DevTools Protocol), drives the Grok web UI through Patchright 
(undetected Playwright fork), and downloads results with custom file naming.

### 4 generation modes

| Mode | Description | Input requirements |
|---|---|---|
| `text_to_image` | Generate images from text prompts | Just prompts |
| `image_to_image` | Transform reference images with prompts | Prompts + ref images |
| `text_to_video` | Generate videos from text prompts | Just prompts |
| `image_to_video` | Animate reference images into videos | Prompts + ref images |

The app **auto-detects** which flow to run based on UI Type setting and 
whether prompts have `ref` field.

### 3 image pick modes (image flows only)

Image generation produces multiple candidates (4 for Quality mode, more for 
Speed mode). User chooses how to pick the "best" one:

| Mode | Behavior | Cost |
|---|---|---|
| `auto` | Always pick first image (index 0) | Free, fast |
| `claude` | Use Claude Code CLI subprocess for vision-based pick | Free with Pro/Max sub |
| `manual` | (Deferred — future) User picks via local dashboard | Free |

Video flows produce only 1 video per submit, so pick mode doesn't apply.

### What it does NOT do

- ❌ Spawn new Chrome instance — only connects to existing browser
- ❌ Use Anthropic API — uses Claude Code CLI subscription quota
- ❌ Headless browser — user keeps browser visible
- ❌ Login/auth automation — user logs in once manually, profile persists

---

## 2. Tech Stack

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Owner's preferred, async support |
| UI framework | PyQt6 | Mature, owner's experience |
| Browser automation | Patchright (async) | Undetected Playwright fork, owner used in past projects |
| Async ↔ Qt bridge | qasync | Required to integrate asyncio with Qt event loop |
| Config validation | pydantic v2 | Type-safe JSON loading |
| Logging | loguru | Better than stdlib |
| Package manager | uv | Fast, reliable, owner's standard |
| Notifications | plyer | Cross-platform desktop notifications |
| AI vision pick | Claude Code CLI subprocess | Free with subscription (no API key) |

---

## 3. Architecture

### Folder structure

```
grok_automation/
├── main.py                       # PyQt6 entry point
├── pyproject.toml                # uv project config
├── README.md                     # User-facing docs
├── CLAUDE.md                     # Project context for Claude Code sessions
├── MASTER_SPEC.md                # This file (single source of truth)
├── launch_brave.bat              # One-click Brave launcher with debug port
├── launch_chrome.bat             # Alternative for Chrome
├── .gitignore
├── .env.example
│
├── grok/                         # All Grok automation logic
│   ├── __init__.py
│   ├── selectors.py              # Selector constants (from snapshots)
│   ├── browser.py                # CDP connect + tab list/select
│   ├── actions.py                # Atomic actions (set_mode, fill_prompt, wait_*, etc.)
│   ├── runner.py                 # Universal flow executor
│   ├── flows.py                  # Declarative flow definitions
│   ├── prompt_loader.py          # Load + normalize JSON
│   ├── claude_picker.py          # Claude CLI subprocess wrapper (TODO)
│   └── error_detector.py         # Rate limit + policy fail detection
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py            # MainWindow with all panels
│   └── panels.py                 # All panel widgets (connection, generation, run, log)
│
├── workers/
│   ├── __init__.py
│   └── automation_worker.py      # QThread bridge with asyncio (qasync)
│
├── examples/                     # Example JSON prompts files
│   ├── prompts_simple.json
│   ├── prompts_with_refs.json
│   └── prompts_eiffel_video.json
│
└── output/                       # Auto-created at runtime
    └── {project_name}/
        ├── candidates/{counter:04d}/    # Per-prompt debug logs (image only)
        │   ├── strip.png
        │   ├── 0.png .. N.png
        │   ├── prompt.txt
        │   ├── meta.json
        │   └── pick.json
        ├── {project}_pic{N}.jpg
        └── {project}_vid{N}.mp4
```

### Architectural principles

1. **Universal runner + declarative flows**: Flows are dicts of action 
   names + params. Adding a new flow = adding a dict, not writing new code.

2. **Atomic actions**: Each action does one thing (set_mode, fill_prompt, 
   click_submit, wait_image_ready, etc.). Composable via flow definitions.

3. **State separation**: 
   - `runner.config` = static config (project name, settings, ref_cache)
   - `runner.state` = dynamic per-run state (counter, current_prompt, vars)

4. **Selector centralization**: All selectors in `grok/selectors.py`. 
   Never hardcode in actions.

5. **No browser spawn**: Always connect via CDP. User controls browser.

6. **Graceful failure**: Exceptions caught at prompt level, app recovers 
   to known state (`/imagine`) before next prompt. Never crash UI.

---

## 4. Browser Setup (CDP)

### One-time setup

User launches browser with debug port via batch file:

```bat
@echo off
set BRAVE_EXE="C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
set PROFILE_DIR="D:\brave-grok-profile"
set DEBUG_PORT=9222

%BRAVE_EXE% ^
  --remote-debugging-port=%DEBUG_PORT% ^
  --user-data-dir=%PROFILE_DIR% ^
  --no-first-run ^
  --no-default-browser-check ^
  --disable-blink-features=AutomationControlled ^
  https://grok.com/imagine
```

**Brave is preferred over Chrome** because:
- Brave Shields block ads/trackers → faster page load
- Chrome with `--remote-debugging-port` + new profile lacks network state cache → slower
- Both use Chromium, Patchright supports both via same CDP API

### Connect from Python

```python
from patchright.async_api import async_playwright

async def connect_cdp(cdp_url: str = "http://localhost:9222"):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(cdp_url)
    return browser, playwright

async def list_tabs(browser):
    tabs = []
    for ctx in browser.contexts:
        for page in ctx.pages:
            tabs.append({
                "url": page.url,
                "title": await page.title()
            })
    return tabs
```

### Verify CDP is running

```
http://localhost:9222/json/version
```

Should return JSON with `Browser`, `webSocketDebuggerUrl` fields.

---

## 5. UI Specification

### MainWindow layout

```
┌──────────────────────────────────────────────────────┐
│  Grok Automation                          [_][□][×] │
├──────────────────────────────────────────────────────┤
│                                                       │
│  ┌─ Connection ──────────────────────────────────┐  │
│  │ CDP URL: [http://localhost:9222         ]    │  │
│  │ [🔌 Connect]   Status: Disconnected/Connected│  │
│  │ Tab: [▾ Select tab...                      ] │  │
│  │ [↻ Refresh tabs]                              │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  ┌─ Generation Settings ──────────────────────────┐  │
│  │ Type:        ● Image  ○ Video                 │  │
│  │                                                │  │
│  │ [Image options]                                │  │
│  │ Quality:     ○ Speed  ● Quality               │  │
│  │ Aspect:      [▾ 16:9]                         │  │
│  │ Pick mode:   ● Auto   ○ Claude                │  │
│  │                                                │  │
│  │ [Video options]                                │  │
│  │ Resolution:  ○ 480p  ● 720p                   │  │
│  │ Duration:    ● 6s    ○ 10s                    │  │
│  │                                                │  │
│  │ Typing speed: ● Fast ○ Human ○ Slow          │  │
│  │ Wait timeout: [60   ] s                       │  │
│  │                                                │  │
│  │ Project name: [______________________]        │  │
│  │ Ref folder:   [____________] [📁 Browse]      │  │
│  │ Prompts JSON: [____________] [📂 Load]        │  │
│  │ Status: 3 prompts (3 with ref)                │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  ┌─ Run ──────────────────────────────────────────┐  │
│  │ [▶ Start]  [■ Stop]   Status: idle/running    │  │
│  │ Progress: ▓▓▓▓░░░░ 4/10                        │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  ┌─ Log ──────────────────────────────────────────┐  │
│  │ [scrollable text panel]                        │  │
│  │ [📂 Open log file] [🗑 Clear]                  │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
└──────────────────────────────────────────────────────┘
```

### UI defaults (hard-coded)

| Field | Default value |
|---|---|
| Type | Image |
| Quality | Quality |
| Aspect | 16:9 |
| Pick mode | Auto |
| Resolution | 720p |
| Duration | 6s |
| Typing speed | Fast |
| Wait timeout | 60s |
| CDP URL | http://localhost:9222 |

### Show/hide rules

| When | Show | Hide |
|---|---|---|
| Type = Image | Quality, Aspect, Pick mode | Resolution, Duration |
| Type = Video | Resolution, Duration, Aspect | Quality, Pick mode |

### Persisted to QSettings

User's last choice for these fields is persisted:
- Project name, Ref folder, Wait timeout, Type, Quality, Aspect, 
  Resolution, Duration, Pick mode, Typing speed

On app restart, restore values automatically.

### Validation before Start

```python
def validate_before_start(settings: dict) -> tuple[bool, str]:
    if not settings["project_name"]:
        return False, "Project name không được rỗng"
    
    if not settings["prompts"]:
        return False, "Chưa load prompts JSON"
    
    # Check ref consistency
    prompts_with_ref = [
        (i+1, p) for i, p in enumerate(settings["prompts"])
        if p.get("ref")
    ]
    
    if prompts_with_ref:
        if not settings.get("ref_folder"):
            return False, (
                f"Có {len(prompts_with_ref)} prompts cần ref ảnh "
                f"nhưng chưa chọn ref folder"
            )
        
        ref_cache = settings.get("ref_cache", {})
        missing = [
            f"Prompt #{idx}: '{p['ref']}'"
            for idx, p in prompts_with_ref
            if p["ref"] not in ref_cache
        ]
        
        if missing:
            return False, "Thiếu ref files:\n" + "\n".join(missing)
    
    return True, ""
```

**No** Video+Claude pick rule — Video flow doesn't call pick_image at all, 
so UI Pick mode value is harmless.

---

## 6. JSON Input Format

### Schema

```json
{
  "prompts": [
    "plain text string prompt",
    { "text": "prompt with ref", "ref": "image_filename.jpg" },
    { "text": "prompt without ref" }
  ]
}
```

### Normalization

`grok/prompt_loader.py` normalizes both string and object items to:

```python
{"text": str, "ref": Optional[str]}
```

```python
def load_prompts(json_path: Path) -> list[dict]:
    data = json.loads(json_path.read_text(encoding='utf-8'))
    raw = data.get("prompts", [])
    
    normalized = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            normalized.append({"text": item, "ref": None})
        elif isinstance(item, dict):
            text = item.get("text", "").strip()
            if not text:
                raise ValueError(f"Prompt #{i+1} missing 'text'")
            normalized.append({
                "text": text,
                "ref": item.get("ref")
            })
        else:
            raise ValueError(f"Prompt #{i+1} invalid type")
    
    if not normalized:
        raise ValueError("No prompts found")
    
    return normalized
```

### Example: text-to-image (no refs)

```json
{
  "prompts": [
    "Eiffel Tower at golden hour, illustration, warm tones",
    "Eiffel Tower at twilight with fireworks, dramatic sky",
    "Eiffel Tower in winter, snow falling softly"
  ]
}
```

### Example: image-to-video (refs match files in ref folder)

```json
{
  "prompts": [
    {
      "text": "Eiffel Tower at golden hour, slow camera zoom in",
      "ref": "eiffel_pic1.jpg"
    },
    {
      "text": "Eiffel Tower at twilight, fireworks bursting in sky",
      "ref": "eiffel_pic2.jpg"
    },
    {
      "text": "Eiffel Tower in winter, snow falling softly",
      "ref": "eiffel_pic3.jpg"
    }
  ]
}
```

### Example: mixed (some with ref, some without)

```json
{
  "prompts": [
    "plain prompt without ref",
    { "text": "with ref", "ref": "lion.jpg" },
    { "text": "without ref but as object" }
  ]
}
```

---

## 7. Selectors Reference

> **Source**: All selectors below were captured from `grok.com/imagine` 
> using a Chrome extension DOM Inspector. Verified via runtime testing 
> as of April 2026.

### `/imagine` — Main page

| Element | Selector | Notes |
|---|---|---|
| Prompt input | `[contenteditable="true"]` | TipTap editor in `<p>`. Empty state has class `is-empty is-editor-empty` |
| Submit button | `button[aria-label^="Submit"]` | Or press Enter on input |
| Upload button | `button[aria-label^="Upload"]` | Opens HTML popup dialog (not OS file picker directly) |
| Generation mode container | `div[aria-label^="Generation mode"]` | Contains Image and Video radio buttons |
| Mode Image button | Use container above + `:has-text("Image")` | Don't use direct `aria-label="Image"` on `/imagine` (that selector only works on result page) |
| Mode Video button | Use container above + `:has-text("Video")` | Same caveat |
| Quality preset buttons | `button[role="radio"]` + filter by text "Speed" or "Quality" | |
| Aspect ratio button | `button[aria-label^="Aspect Ratio"]` | Click opens dropdown |
| Aspect option | `div[role="menuitem"]` + filter by text "16:9", "1:1", etc. | Text format: "16:9\nWidescreen" |
| Video resolution group | `div[aria-label="Video resolution"]` | Contains 480p/720p radios. Visible only in Video mode. |
| Video duration group | `div[aria-label="Video duration"]` | Contains 6s/10s radios. Visible only in Video mode. |

### `/imagine/post/{uuid}` — Result page

| Element | Selector | Notes |
|---|---|---|
| Download button | `button[aria-label^="Download"]` | Same selector for both image and video result |
| Back button | `div[aria-label^="Back"]` | Note: `<div>` not `<button>` |
| Redo image | `button[aria-label^="Redo image"]` | Image only |
| Make video | `button[aria-label^="Make video"]` | Image only |
| Play | `button[aria-label^="Play"]` | Has text "More" |
| Video element (when ready) | `#sd-video` | `<video>` element. Existence = video ready. |

### Upload popup (after clicking Upload button)

| Element | Selector | Notes |
|---|---|---|
| Drop zone button | `button:has-text("Upload or drop images")` | Inside popup. Don't click — bypass via input below. |
| Hidden file input | `input[type="file"]` | After popup opens, this exists. Use `set_input_files()` directly. |

### Image generation state (CRITICAL)

| State | Detection |
|---|---|
| Generating (blur) | `[role="listitem"] canvas` exists |
| Ready (clickable) | `[role="listitem"]` contains NO `<canvas>` child |
| New masonry section | `#imagine-masonry-section-{N}` where N increments per submit |

**Key insight**: The class `img.opacity-1` appears IMMEDIATELY when low-res 
placeholder loads, BEFORE `<canvas>` overlay disappears. Don't use 
`img.opacity-1` as ready indicator. Use absence-of-canvas instead.

### Video generation state

| State | Detection |
|---|---|
| Generating | `<div>` with text matching `/Generating\s+\d+%/` exists |
| Ready | `<video id="sd-video">` exists AND no overlay above |
| Cancel button | `<button>` with text "Cancel Video" (don't click — wait only) |

### Toast notifications (errors)

| Element | Selector |
|---|---|
| Any toast | `[data-sonner-toast]` |
| Rate limit text | Toast with text matching `/rate limit\|too many\|quota/i` |
| Policy fail text | Toast with text matching `/violat\|policy\|inappropriate\|blocked/i` |

---

## 8. DOM State Patterns

### Image generation lifecycle

```
T=0s:   Submit clicked
T=0-1s: New masonry section #N appears (empty initially)
T=1-N:  Listitems populate one by one with <canvas> overlays
        - <img class="opacity-1"> with low-res placeholder loads under canvas
        - Canvas covers img while generation runs
T=N:    For each generated image, <canvas> is removed
        - Listitem now has only <img.opacity-1> with full-res content
        - This listitem is "ready" (clickable)
T=N+M:  All target_count listitems ready (Quality: 4, Speed: 8)
        - Code can proceed to pick + click
```

**Detector**: count listitems WITHOUT canvas child:

```python
listitems = masonry.locator('[role="listitem"]')
total = await listitems.count()
ready = 0
for i in range(total):
    has_canvas = await listitems.nth(i).locator('canvas').count()
    if has_canvas == 0:
        ready += 1
```

### Video generation lifecycle

```
T=0s:    Submit clicked
T=0-2s:  Page navigates from /imagine to /imagine/post/{uuid}
T=0-15s: ⚠️ NO overlay yet — Grok rendering result page
T=15s:   "Generating X%" overlay appears (initial X = 5)
T=15-N:  Progress increments (15s pollings recommended)
         - Two overlays exist: main player overlay + thumbnail mini overlay
         - Both contain text matching /Generating \d+%/
T=N:     Both overlays disappear
         - <video id="sd-video"> element appears in DOM
         - This is the ready state
T=N+1s:  Download button is clickable
```

**Wait pattern**:

```python
# Phase 1: Fixed sleep to let overlay appear (Grok needs ~10-15s after submit)
await asyncio.sleep(20)

# Phase 2: Poll until overlay gone AND video element exists
while time < timeout:
    overlay_count = await locator(div, has_text=/Generating \d+%/).count()
    if overlay_count == 0:
        video_count = await locator('#sd-video').count()
        if video_count > 0:
            return ready
    await sleep(2)
```

### Upload flow (image-to-X modes)

```
1. User triggers upload (action: upload_ref_if_present)
2. Click button[aria-label^="Upload"]
3. HTML popup dialog appears (NOT OS file picker)
   - Contains drop zone with hidden <input type="file">
4. set_input_files(path) on hidden input → bypasses OS dialog
5. Popup closes, preview thumbnail renders in prompt bar
   - Can take 5-30s for full processing (especially video mode)
6. Wait for preview → safe to fill prompt + submit
```

### Page transition between prompts

```
After download of prompt #N:
  Current URL: /imagine/post/{uuid}
  
For prompt #N+1, must navigate back to /imagine:
  Method 1: Click div[aria-label^="Back"] (preferred)
  Method 2: page.goto("https://grok.com/imagine") (fallback)
  
After navigation, MUST wait for UI to render:
  await locator('div[aria-label^="Generation mode"]').wait_for(state="visible")
  
Otherwise set_mode call will timeout because dropdown not yet visible.
```

---

## 9. Atomic Actions

### Action signature pattern

All actions are async methods on a class (or module-level functions) that 
take `self` (with access to `self.page`, `self.config`, `self.runner`):

```python
async def action_name(self, param1: type = default, param2: type = default):
    """Description."""
    # Implementation
    pass
```

### Action: `ensure_at(url)`

Navigate to URL if not there. Robust recovery from `/post/{uuid}` state.

```python
async def ensure_at(self, url: str):
    target = url if url.startswith("/") else f"/{url}"
    
    if target not in self.page.url:
        navigated = False
        
        if "/post/" in self.page.url:
            try:
                back = self.page.locator('div[aria-label^="Back"]')
                if await back.count() > 0:
                    await back.first.click(timeout=5000)
                    await self.page.wait_for_url(f"**{target}", timeout=10000)
                    navigated = True
            except Exception as e:
                log.warning(f"Back click failed: {e}")
        
        if not navigated:
            await self.page.goto(f"https://grok.com{target}", timeout=30000)
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
    
    # CRITICAL: wait for UI element before proceeding
    await self.page.locator('div[aria-label^="Generation mode"]').wait_for(
        state="visible", timeout=15000
    )
    await asyncio.sleep(0.5)
```

### Action: `set_mode(value)`

Click "Image" or "Video" radio. Use container as anchor (selector 
`button[aria-label="Image"]` only works on result page, not main).

```python
async def set_mode(self, value: str):
    group = self.page.locator('div[aria-label^="Generation mode"]')
    await group.wait_for(state="visible", timeout=10000)
    
    target_text = value.capitalize()  # "Image" or "Video"
    btn = group.locator(f'button:has-text("{target_text}")').first
    await btn.click()
    await asyncio.sleep(0.5)
```

### Action: `set_quality(value)` (image only)

```python
async def set_quality(self, value: str):
    btns = self.page.locator('button[role="radio"]')
    n = await btns.count()
    for i in range(n):
        text = (await btns.nth(i).text_content() or "").strip()
        if text.lower() == value.lower():
            await btns.nth(i).click()
            await asyncio.sleep(0.5)
            return
    raise RuntimeError(f"Quality preset '{value}' not found")
```

### Action: `set_aspect(value)`

```python
async def set_aspect(self, value: str):
    # Open dropdown
    await self.page.locator('button[aria-label^="Aspect Ratio"]').click()
    await asyncio.sleep(0.5)
    
    # Click matching option
    options = self.page.locator('div[role="menuitem"]')
    n = await options.count()
    for i in range(n):
        text = (await options.nth(i).text_content() or "").strip()
        if text.startswith(value):  # "16:9\nWidescreen" startswith "16:9"
            await options.nth(i).click()
            return
    raise RuntimeError(f"Aspect '{value}' not found")
```

### Action: `set_video_resolution(value)`

```python
async def set_video_resolution(self, value: str):
    """value: '480p' or '720p'"""
    group = self.page.locator('div[aria-label="Video resolution"]')
    radios = group.locator('button[role="radio"]')
    idx = 0 if value == "480p" else 1
    await radios.nth(idx).click()
    await asyncio.sleep(0.3)
```

### Action: `set_video_duration(value)`

```python
async def set_video_duration(self, value: str):
    """value: '6s' or '10s'"""
    group = self.page.locator('div[aria-label="Video duration"]')
    radios = group.locator('button[role="radio"]')
    idx = 0 if value == "6s" else 1
    await radios.nth(idx).click()
    await asyncio.sleep(0.3)
```

### Action: `verify_input_empty()`

```python
async def verify_input_empty(self):
    await self.page.wait_for_selector(
        'p.is-empty.is-editor-empty', timeout=5000
    )
```

### Action: `fill_prompt(value)`

Type with human-like delay configurable by speed mode.

```python
TYPING_DELAYS = {
    "fast":  (10, 25),
    "human": (40, 110),
    "slow":  (80, 200),
}

async def fill_prompt(self, value: str):
    speed = self.config.get("typing_speed", "fast")
    min_d, max_d = TYPING_DELAYS.get(speed, TYPING_DELAYS["fast"])
    
    await self.page.click('[contenteditable="true"]')
    await asyncio.sleep(random.uniform(0.2, 0.4))
    
    delay = random.randint(min_d, max_d)
    await self.page.type('[contenteditable="true"]', value, delay=delay)
```

### Action: `upload_ref_if_present(value)`

Upload via direct hidden input (bypass popup's "Upload or drop" button).

```python
async def upload_ref_if_present(self, value: str = None):
    if not value:
        log.debug("No ref, skip upload")
        return
    
    ref_cache = self.config.get("ref_cache", {})
    full_path = ref_cache.get(value)
    if not full_path:
        raise RuntimeError(f"Ref '{value}' not in cache")
    
    # Step 1: Click Upload button to open popup
    upload_btn = self.page.locator('button[aria-label^="Upload"]')
    await upload_btn.wait_for(state="visible", timeout=10000)
    await upload_btn.click()
    await asyncio.sleep(0.5)
    
    # Step 2: Set file directly on hidden input (bypass OS picker)
    file_input = self.page.locator('input[type="file"]').first
    if await self.page.locator('input[type="file"]').count() == 0:
        raise RuntimeError("No file input found after Upload click")
    
    await file_input.set_input_files(str(full_path))
    
    # Step 3: Wait for upload preview to render (can take 5-30s for video)
    # TODO: implement smarter detection. For now, fixed sleep.
    await asyncio.sleep(15)
    log.info(f"Ref uploaded: {value}")
```

### Action: `click_submit()`

```python
async def click_submit(self):
    await self.page.locator('button[aria-label^="Submit"]').click()
```

### Action: `submit_and_wait_ready(target_count, timeout_ms)` (image flows)

Combined action: submit + wait for new masonry to have N ready listitems.

```python
async def submit_and_wait_ready(
    self, target_count: int = 4, timeout_ms: int = 60000
):
    # Snapshot masonry count BEFORE submit
    initial_sections = await self.page.locator(
        '[id^="imagine-masonry-section-"]'
    ).count()
    
    # Submit
    await self.page.locator('button[aria-label^="Submit"]').click()
    log.info(f"Submitted. Waiting for masonry #{initial_sections}...")
    
    start = time.time()
    last_ready = 0
    
    while (time.time() - start) * 1000 < timeout_ms:
        current = await self.page.locator(
            '[id^="imagine-masonry-section-"]'
        ).count()
        
        if current <= initial_sections:
            await asyncio.sleep(0.5)
            continue
        
        new_masonry = self.page.locator(
            '[id^="imagine-masonry-section-"]'
        ).nth(initial_sections)
        
        listitems = new_masonry.locator('[role="listitem"]')
        total = await listitems.count()
        
        ready = 0
        for i in range(total):
            has_canvas = await listitems.nth(i).locator('canvas').count()
            if has_canvas == 0:
                ready += 1
        
        last_ready = ready
        
        if ready >= target_count:
            return {
                "ok": True,
                "ready_count": ready,
                "masonry_index": initial_sections
            }
        
        err = await self.detect_error()
        if err:
            return {"ok": False, "ready_count": ready, **err}
        
        await asyncio.sleep(1)
    
    return {"ok": False, "reason": "timeout", "ready_count": last_ready}
```

### Action: `wait_video_ready(initial_wait_s, timeout_ms)` (video flows)

```python
async def wait_video_ready(
    self, initial_wait_s: int = 20, timeout_ms: int = 300000
):
    import re
    
    log.info(f"Waiting fixed {initial_wait_s}s for overlay to appear...")
    await asyncio.sleep(initial_wait_s)
    
    log.info("Polling for video completion...")
    start = time.time()
    last_pct = -1
    
    while (time.time() - start) * 1000 < timeout_ms:
        overlays = self.page.locator('div').filter(
            has_text=re.compile(r'Generating\s+\d+%')
        )
        count = await overlays.count()
        
        if count == 0:
            # Confirm by checking for video element
            video_count = await self.page.locator('#sd-video').count()
            if video_count > 0:
                log.info("Video ready (sd-video element present)")
                await asyncio.sleep(1)
                return {"ok": True}
        
        try:
            text = await overlays.first.text_content() if count > 0 else ""
            match = re.search(r'(\d+)%', text or '')
            if match:
                pct = int(match.group(1))
                if pct != last_pct:
                    log.info(f"Video progress: {pct}%")
                    last_pct = pct
        except:
            pass
        
        err = await self.detect_error()
        if err:
            return {"ok": False, **err}
        
        await asyncio.sleep(2)
    
    return {"ok": False, "reason": "gen_timeout", "last_progress": last_pct}
```

### Action: `save_candidates_log(target_count)` (image flows only)

Save debug log: viewport screenshot + individual images + meta.

```python
async def save_candidates_log(self, target_count: int = 4):
    counter = self.runner.state["counter"]
    project = self.config["project_name"]
    prompt_text = self.runner.state["current_prompt"]["text"]
    masonry_index = self.runner.state["vars"].get(
        "ready_result", {}
    ).get("masonry_index", 0)
    
    candidates_dir = Path(f"output/{project}/candidates/{counter:04d}")
    candidates_dir.mkdir(parents=True, exist_ok=True)
    
    # Strip screenshot
    try:
        await self.page.screenshot(path=str(candidates_dir / "strip.png"))
    except Exception as e:
        log.warning(f"Strip screenshot failed: {e}")
    
    # Individual images
    masonry = self.page.locator(
        '[id^="imagine-masonry-section-"]'
    ).nth(masonry_index)
    listitems = masonry.locator('[role="listitem"]')
    total = await listitems.count()
    
    saved = 0
    for i in range(min(total, target_count)):
        try:
            has_canvas = await listitems.nth(i).locator('canvas').count()
            if has_canvas == 0:
                img = listitems.nth(i).locator('img.opacity-1').first
                img_bytes = await img.screenshot()
                (candidates_dir / f"{i}.png").write_bytes(img_bytes)
                saved += 1
        except Exception as e:
            log.warning(f"Failed candidate {i}: {e}")
    
    # Prompt + meta
    (candidates_dir / "prompt.txt").write_text(prompt_text, encoding='utf-8')
    
    meta = {
        "counter": counter,
        "prompt": prompt_text,
        "target_count": target_count,
        "masonry_index": masonry_index,
        "saved_candidates": saved,
        "pick_mode": self.config.get("pick_mode", "auto"),
        "timestamp": datetime.now().isoformat()
    }
    (candidates_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8'
    )
```

### Action: `pick_image()` (image flows only)

Dispatch by pick_mode, always save pick.json.

```python
async def pick_image(self) -> int:
    counter = self.runner.state["counter"]
    project = self.config["project_name"]
    candidates_dir = Path(f"output/{project}/candidates/{counter:04d}")
    candidates_dir.mkdir(parents=True, exist_ok=True)
    
    pick_mode = self.config.get("pick_mode", "auto")
    
    if pick_mode == "auto":
        choice = 0
        pick_data = {"choice": 0, "mode": "auto",
                     "reason": "First image (auto)"}
    elif pick_mode == "claude":
        log.warning("Claude pick TODO, fallback to 0")
        choice = 0
        pick_data = {"choice": 0, "mode": "claude_fallback",
                     "reason": "Not implemented"}
    else:
        choice = 0
        pick_data = {"choice": 0, "mode": "unknown"}
    
    pick_data["timestamp"] = datetime.now().isoformat()
    
    (candidates_dir / "pick.json").write_text(
        json.dumps(pick_data, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    
    return choice
```

### Action: `click_image(index, masonry_index)` (image flows only)

Click ready listitem (no canvas overlay). Uses listitem itself, not 
inner `<img>` (Grok binds click handler at listitem level).

```python
async def click_image(self, index: int, masonry_index: int = None):
    if masonry_index is not None:
        masonry = self.page.locator(
            '[id^="imagine-masonry-section-"]'
        ).nth(masonry_index)
    else:
        masonry = self.page.locator(
            '[id^="imagine-masonry-section-"]'
        ).last
    
    listitems = masonry.locator('[role="listitem"]')
    total = await listitems.count()
    
    ready_indices = []
    for i in range(total):
        has_canvas = await listitems.nth(i).locator('canvas').count()
        if has_canvas == 0:
            ready_indices.append(i)
    
    if not ready_indices:
        raise RuntimeError("No ready listitem")
    
    if index >= len(ready_indices):
        log.warning(f"Index {index} OOR ({len(ready_indices)} ready)")
        index = 0
    
    real_idx = ready_indices[index]
    target = listitems.nth(real_idx)
    await target.click()
```

### Action: `wait_url_match(pattern)`

```python
async def wait_url_match(self, pattern: str):
    await self.page.wait_for_url(f"**{pattern}**", timeout=15000)
```

### Action: `download(prefix)`

Click Download button, save with custom name.

```python
async def download(self, prefix: str = "pic"):
    project = self.config["project_name"]
    counter = self.runner.state["counter"]
    
    btn = self.page.locator('button[aria-label^="Download"]')
    btn_count = await btn.count()
    if btn_count == 0:
        raise RuntimeError(f"Download button not found at {self.page.url}")
    
    async with self.page.expect_download(timeout=60000) as dl_info:
        await btn.first.click()
    download = await dl_info.value
    
    ext = download.suggested_filename.split('.')[-1]
    target = Path(f"output/{project}/{project}_{prefix}{counter}.{ext}")
    target.parent.mkdir(parents=True, exist_ok=True)
    
    await download.save_as(str(target))
    
    if not target.exists():
        return {"ok": False, "reason": "file_not_saved"}
    
    return {"ok": True, "path": str(target)}
```

### Action: `click_back()`

```python
async def click_back(self):
    back_div = self.page.locator('div[aria-label^="Back"]')
    if await back_div.count() > 0:
        await back_div.first.click()
        return
    
    # Fallback: button variant
    back_btn = self.page.locator('button[aria-label^="Back"]')
    if await back_btn.count() > 0:
        await back_btn.first.click()
        return
    
    # Last resort: direct goto
    await self.page.goto("https://grok.com/imagine")
```

### Action: `detect_error()`

```python
async def detect_error(self):
    toasts = self.page.locator('[data-sonner-toast]')
    n = await toasts.count()
    for i in range(n):
        text = (await toasts.nth(i).text_content() or "").lower()
        if any(k in text for k in ["rate limit", "too many", "quota"]):
            return {"type": "rate_limit", "msg": text}
        if any(k in text for k in ["violat", "policy", "inappropriate", "blocked"]):
            return {"type": "policy_fail", "msg": text}
    return None
```

---

## 10. Flows

Flows are **declarative dicts** that the runner executes. Each step 
is an action call with optional parameter resolution.

### Flow: `text_to_image`

```python
"text_to_image": {
    "name": "Text-to-Image",
    "loop_per_prompt": True,
    "steps": [
        {"action": "ensure_at", "url": "/imagine"},
        {"action": "set_mode", "value": "image"},
        {"action": "set_quality", "from_config": "quality"},
        {"action": "set_aspect", "from_config": "aspect"},
        {"action": "verify_input_empty"},
        {"action": "fill_prompt", "from_prompt": "text"},
        {"action": "submit_and_wait_ready",
         "target_count_from_config": "target_count",
         "save_to": "ready_result"},
        {"action": "save_candidates_log",
         "target_count_from_config": "target_count"},
        {"action": "pick_image", "save_to": "best_idx"},
        {"action": "click_image",
         "from_var": "best_idx",
         "masonry_from_var": "ready_result.masonry_index"},
        {"action": "wait_url_match", "pattern": "/post/"},
        {"action": "download", "prefix": "pic"},
        {"action": "click_back"},
        {"action": "wait_url_match", "pattern": "/imagine"},
    ],
}
```

### Flow: `image_to_image`

```python
"image_to_image": {
    "name": "Image-to-Image",
    "loop_per_prompt": True,
    "steps": [
        {"action": "ensure_at", "url": "/imagine"},
        {"action": "set_mode", "value": "image"},
        {"action": "set_quality", "from_config": "quality"},
        {"action": "set_aspect", "from_config": "aspect"},
        {"action": "upload_ref_if_present", "from_prompt": "ref"},
        {"action": "fill_prompt", "from_prompt": "text"},
        {"action": "submit_and_wait_ready",
         "target_count_from_config": "target_count",
         "save_to": "ready_result"},
        {"action": "save_candidates_log",
         "target_count_from_config": "target_count"},
        {"action": "pick_image", "save_to": "best_idx"},
        {"action": "click_image",
         "from_var": "best_idx",
         "masonry_from_var": "ready_result.masonry_index"},
        {"action": "wait_url_match", "pattern": "/post/"},
        {"action": "download", "prefix": "pic"},
        {"action": "click_back"},
    ],
}
```

### Flow: `text_to_video`

```python
"text_to_video": {
    "name": "Text-to-Video",
    "loop_per_prompt": True,
    "steps": [
        {"action": "ensure_at", "url": "/imagine"},
        {"action": "set_mode", "value": "video"},
        {"action": "set_video_resolution", "from_config": "resolution"},
        {"action": "set_video_duration", "from_config": "duration"},
        {"action": "set_aspect", "from_config": "aspect"},
        {"action": "fill_prompt", "from_prompt": "text"},
        {"action": "click_submit"},
        {"action": "wait_url_match", "pattern": "/post/"},
        {"action": "wait_video_ready"},
        {"action": "download", "prefix": "vid"},
        {"action": "click_back"},
    ],
}
```

### Flow: `image_to_video`

```python
"image_to_video": {
    "name": "Image-to-Video",
    "loop_per_prompt": True,
    "steps": [
        {"action": "ensure_at", "url": "/imagine"},
        {"action": "set_mode", "value": "video"},
        {"action": "set_video_resolution", "from_config": "resolution"},
        {"action": "set_video_duration", "from_config": "duration"},
        {"action": "set_aspect", "from_config": "aspect"},
        {"action": "upload_ref_if_present", "from_prompt": "ref"},
        {"action": "fill_prompt", "from_prompt": "text"},
        {"action": "click_submit"},
        {"action": "wait_url_match", "pattern": "/post/"},
        {"action": "wait_video_ready"},
        {"action": "download", "prefix": "vid"},
        {"action": "click_back"},
    ],
}
```

### Flow auto-selection

```python
def determine_flow(settings: dict) -> str:
    type_ = settings["type"]
    has_any_ref = any(p.get("ref") for p in settings["prompts"])
    
    if type_ == "image":
        return "image_to_image" if has_any_ref else "text_to_image"
    else:
        return "image_to_video" if has_any_ref else "text_to_video"

def get_target_count(settings: dict) -> int:
    """Hard-coded: Quality=4, Speed=8 (image only). Video=1."""
    if settings["type"] != "image":
        return 1
    return 4 if settings["quality"] == "quality" else 8
```

### Runner

```python
class FlowRunner:
    def __init__(self, actions, config: dict, prompts: list):
        self.actions = actions
        self.config = config
        self.prompts = prompts
        self.state = {
            "counter": 0,
            "current_prompt": None,
            "vars": {}
        }
        self._stop = False
    
    async def run(self, flow_name: str):
        flow = FLOWS[flow_name]
        
        for idx, prompt in enumerate(self.prompts):
            if self._stop:
                break
            
            self.state["counter"] = idx + 1
            self.state["current_prompt"] = prompt
            
            log.info(f"[{idx+1}/{len(self.prompts)}] Prompt: {prompt['text'][:80]}...")
            
            try:
                await self._execute_steps(flow["steps"])
                log.info(f"[{idx+1}/{len(self.prompts)}] Success")
            except Exception as e:
                log.error(f"[{idx+1}/{len(self.prompts)}] FAILED: {e}")
                
                # Recovery: navigate back to /imagine for next prompt
                try:
                    await self.actions.page.goto(
                        "https://grok.com/imagine", timeout=15000
                    )
                    await asyncio.sleep(2)
                except Exception as recovery_error:
                    log.error(f"Recovery failed: {recovery_error}")
                
                continue
    
    async def _execute_steps(self, steps: list):
        for step in steps:
            if self._stop:
                return
            
            action_name = step["action"]
            kwargs = self._resolve_params(step)
            
            log.debug(f">>> {action_name}({kwargs})")
            handler = getattr(self.actions, action_name)
            result = await handler(**kwargs)
            
            if "save_to" in step and result is not None:
                self.state["vars"][step["save_to"]] = result
    
    def _resolve_params(self, step):
        kwargs = {}
        for k, v in step.items():
            if k in ("action", "save_to"):
                continue
            
            if k == "from_prompt":
                kwargs["value"] = self.state["current_prompt"].get(v)
            elif k == "from_config":
                kwargs["value"] = self.config.get(v)
            elif k == "from_var":
                kwargs["value"] = self._resolve_var(v)
            elif k.endswith("_from_config"):
                base = k.replace("_from_config", "")
                kwargs[base] = self.config.get(v)
            elif k.endswith("_from_var"):
                base = k.replace("_from_var", "")
                kwargs[base] = self._resolve_var(v)
            else:
                kwargs[k] = v
        return kwargs
    
    def _resolve_var(self, key: str):
        """Support 'foo.bar' nested access."""
        if "." in key:
            parts = key.split(".")
            val = self.state["vars"].get(parts[0], {})
            for p in parts[1:]:
                if isinstance(val, dict):
                    val = val.get(p)
                else:
                    return None
            return val
        return self.state["vars"].get(key)
    
    def stop(self):
        self._stop = True
```

---

## 11. Error Handling

### Error categories

| Category | Detection | Strategy |
|---|---|---|
| Rate limit | Toast text matches `/rate limit\|too many\|quota/i` | Retry 3x with backoff (60s, 180s, 600s), then pause |
| Policy fail | Toast text matches `/violat\|policy\|inappropriate/i` | Log, skip prompt, continue |
| Timeout (no result) | wait_*_ready timeout | Skip, continue next |
| Browser disconnect | Patchright exception "Target closed" | Reconnect, retry from current step |
| UI element not found | Wait_for_selector timeout | Take screenshot, log, skip |
| Download fail | expect_download timeout | Retry once, then skip |

### Recovery mechanism (per-prompt)

```python
for prompt in prompts:
    try:
        execute_flow_steps(prompt)
    except Exception as e:
        log.error(...)
        # Force navigate to known clean state
        await page.goto("https://grok.com/imagine")
        await asyncio.sleep(2)
        continue  # Next prompt
```

### Notifications (TODO — Batch 2 not yet implemented)

When timeout occurs, send desktop notification via `plyer`:

```python
from plyer import notification
notification.notify(
    title="Grok Automation",
    message=f"Prompt #{n} timeout. Retrying...",
    timeout=10
)
```

---

## 12. Output Structure

### Per-project folder

```
output/
└── {project_name}/
    ├── candidates/                ← image flows only
    │   ├── 0001/
    │   │   ├── strip.png          ← viewport screenshot
    │   │   ├── 0.png .. N.png    ← individual element screenshots
    │   │   ├── prompt.txt         ← original prompt
    │   │   ├── meta.json          ← target_count, masonry_index, etc.
    │   │   └── pick.json          ← {choice, mode, reason}
    │   ├── 0002/
    │   └── 0003/
    ├── {project}_pic1.jpg         ← image downloads
    ├── {project}_pic2.jpg
    ├── {project}_vid1.mp4         ← video downloads
    └── {project}_vid2.mp4
```

### Naming convention

- Image: `{project_name}_pic{counter}.{ext}` where counter starts at 1
- Video: `{project_name}_vid{counter}.{ext}`
- Counter resets each run (not persisted across sessions)

### Meta file format

```json
{
  "counter": 1,
  "prompt": "Eiffel Tower at golden hour...",
  "target_count": 4,
  "masonry_index": 0,
  "saved_candidates": 4,
  "pick_mode": "auto",
  "timestamp": "2026-04-26T10:30:00.000Z"
}
```

### Pick file format

```json
{
  "choice": 0,
  "mode": "auto",
  "reason": "First image (auto mode)",
  "timestamp": "2026-04-26T10:30:05.000Z"
}
```

---

## 13. Coding Conventions

### Language

- **User-facing strings**: Vietnamese (UI labels, log messages, errors)
- **Code, comments, docstrings**: English
- **Variable names**: English
- **Commit messages**: English

### Async style

- All Patchright calls async
- Use `qasync` to bridge with PyQt6 event loop
- Never use sync API

### Error patterns

```python
# Don't crash UI:
try:
    result = await some_action()
except Exception as e:
    log.error(f"Action failed: {e}")
    return {"ok": False, "reason": str(e)}

# DO raise from inside actions for runner to catch:
async def some_action(self):
    if not condition:
        raise RuntimeError("Specific failure reason")
```

### State management

- All state in `runner.state` dict
- No globals
- Config is read-only after init
- Actions don't mutate state directly except via `save_to` mechanism

### Selectors

- All in `grok/selectors.py` as constants
- Use `^=` prefix matching for resilience to text changes
- Document source (which snapshot file) in comments

### Logging

```python
from loguru import logger as log

log.debug("Detailed state info")
log.info("User-facing progress")
log.warning("Recoverable issue")
log.error("Unrecoverable failure")
```

---

## 14. Testing Strategy

### Manual testing tiers

**Tier 1 — Quick smoke test (1 prompt)**:
- Edit JSON to 1 prompt
- Run with default settings
- Verify file output

**Tier 2 — Multi-prompt (3 prompts)**:
- Test transitions between prompts
- Check no cascading failures

**Tier 3 — Mode coverage**:
- Run all 4 flows × 2 quality presets (Quality, Speed)
- Verify each generates correctly

**Tier 4 — Error injection**:
- Disconnect Wi-Fi mid-gen → verify retry/skip
- Submit known-bad prompt → verify policy fail handling
- Manually close browser tab → verify reconnect

### What to verify per run

| Check | How |
|---|---|
| Files generated | `dir output/{project}/` |
| Candidates folder (image) | Has strip.png + N.png + meta + pick |
| Naming correct | Sequential counter, correct extension |
| Logs clean | No exceptions, no silent failures |

---

## 15. Known Issues & Quirks

### Quirk 1: `img.opacity-1` is misleading

This class appears immediately when low-res placeholder loads, BEFORE 
the `<canvas>` overlay is removed. Don't use it as ready indicator. 
Use absence-of-canvas instead.

### Quirk 2: Upload flow has 2 layers

Click Upload button does NOT open OS file picker directly. It opens 
HTML popup dialog with drop zone. Use `set_input_files()` on hidden 
`<input type="file">` to bypass.

### Quirk 3: Video gen has 10-15s delay before overlay appears

After Submit + page navigates to /post/, NO "Generating X%" overlay 
exists for 10-15 seconds. Must wait fixed period before polling, 
otherwise immediate poll returns "ready" falsely.

### Quirk 4: Mode buttons differ between pages

`button[aria-label="Image"]` works on `/post/` result page but NOT 
on `/imagine` main page. Use `div[aria-label="Generation mode"]` 
container as anchor + filter by text.

### Quirk 5: Aspect dropdown auto-closes on selection

After clicking Aspect Ratio button to open dropdown, click any 
`div[role="menuitem"]` will both select and close. No need for 
separate close action.

### Quirk 6: TipTap editor empty state

Empty prompt input has class `is-empty is-editor-empty` on the inner 
`<p>` element. Use this to verify input is ready for new prompt 
(prevents leftover text from previous interactions).

### Quirk 7: Grok rate limit affects only Quality mode often

Speed mode is more reliable when Grok is overloaded. If Quality times 
out, switch to Speed and continue testing.

### Quirk 8: Brave preferred over Chrome for CDP

Chrome with new profile + remote-debugging-port has slower network. 
Brave handles this better with built-in Shields. Patchright works 
identically with either.

### Quirk 9: Direct img click doesn't navigate

In image masonry, clicking the `<img>` element directly may not 
trigger Grok's navigation handler. Click the `[role="listitem"]` 
container instead — handler is bound there.

### Quirk 10: Multiple "Generating X%" overlays exist

Video result page has TWO overlays during gen:
1. Main video player overlay (large, center)
2. Thumbnail mini overlay (small, sidebar)

Both contain "Generating X%" text. The detection regex catches both. 
Wait for count to reach 0 (both gone).

---

## Quick Start for AI/Developer

To rebuild this project from scratch:

1. Read sections 1-3 to understand purpose and architecture
2. Set up environment per section 2 (uv, Python 3.11+, PyQt6, Patchright)
3. Read section 4 to understand CDP connection
4. Build UI per section 5
5. Implement actions per section 9 using selectors from section 7
6. Wire flows per section 10 with runner pattern
7. Add error handling per section 11
8. Test per section 14 starting with Tier 1

For existing project maintenance:

1. Read sections 7-9 to understand current selectors and actions
2. Check section 15 for known quirks before debugging
3. Use section 8 for understanding DOM state during automation

---

## End of Master Spec

**Maintenance**: Update this document when:
- New selectors discovered (add to section 7)
- New actions added (add to section 9)
- New flows created (add to section 10)
- New quirks discovered (add to section 15)

**Single source of truth**: This file should be the most up-to-date 
reference. Other docs (CLAUDE.md, README.md, fix batches) supplement 
but don't supersede this spec.
