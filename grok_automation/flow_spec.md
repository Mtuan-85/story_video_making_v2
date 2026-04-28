# Flow Spec — Grok Automation

> Detailed specifications for all 4 generation modes × 3 pick modes.
> Source: 5 inspector snapshot files + 3 recordings on grok.com/imagine.

---

## Common steps (shared across flows)

### `ensure_at(url)`
Navigate to URL if not already there. If currently on `/imagine/post/{uuid}`, click Back first.

```python
if target_url not in page.url:
    if "/post/" in page.url:
        await page.locator(SEL.BACK).click()
    await page.wait_for_url(f"**{target_url}", timeout=10000)
```

### `verify_input_empty()`
Wait for prompt input to be in empty state.

```python
await page.wait_for_selector('p.is-empty.is-editor-empty', timeout=5000)
```

### `fill_prompt(text)`
Click input, type text with human-like delay.

```python
await page.click('[contenteditable="true"]')
await asyncio.sleep(random.uniform(0.3, 0.6))
await page.type('[contenteditable="true"]', text, delay=random.randint(40, 110))
```

### `click_submit()`
Click Submit button (or press Enter — both work).

```python
await page.locator('button[aria-label^="Submit"]').click()
# Alternative: await page.keyboard.press('Enter')
```

### `wait_image_ready(timeout=60000)`
Poll until 4 canvas → img.opacity-1 transition.

```python
start = time.time() * 1000
while (time.time() * 1000 - start) < timeout:
    canvas = await page.locator('[role="listitem"] canvas').count()
    ready = await page.locator('[role="listitem"] img.opacity-1').count()
    if canvas == 0 and ready > 0:
        return {"ok": True, "count": ready}
    
    err = await detect_error(page)
    if err: return {"ok": False, **err}
    
    await asyncio.sleep(0.5)
return {"ok": False, "reason": "timeout"}
```

### `click_image(idx)`
Click the Nth image in the latest masonry section.

```python
masonry = page.locator('[id^="imagine-masonry-section-"]').last
imgs = masonry.locator('img.opacity-1')
await imgs.nth(idx).click()
```

### `download(naming)`
Click Download button, intercept download, save with custom name.

```python
async with page.expect_download() as dl_info:
    await page.locator('button[aria-label^="Download"]').click()
download = await dl_info.value

ext = download.suggested_filename.split('.')[-1]
filename = naming.format(**state)  # e.g. "{project}_pic{counter}"
target = output_dir / project / f"{filename}.{ext}"
target.parent.mkdir(parents=True, exist_ok=True)
await download.save_as(str(target))
```

### `click_back()`
Click Back from result page back to /imagine.

```python
await page.locator('div[aria-label^="Back"]').click()
await page.wait_for_url("**/imagine", timeout=10000)
```

### `set_mode(value)`
Toggle between Image and Video mode.

```python
selector = f'button[aria-label^="{value.capitalize()}"][role="radio"]'
btn = page.locator(selector)
# Check if already active (aria-pressed or visual state)
await btn.click()
await asyncio.sleep(0.5)
```

### `set_quality(value)` (Image mode only)
Click "Speed" or "Quality" radio.

```python
# Filter button[role="radio"] by text content
btns = page.locator('button[role="radio"]')
n = await btns.count()
for i in range(n):
    text = (await btns.nth(i).text_content() or "").strip()
    if text.lower() == value.lower():
        await btns.nth(i).click()
        return
```

### `set_aspect(value)` (16:9, 9:16, 1:1, 3:2, 2:3)
Open dropdown → click matching option.

```python
# Open dropdown
await page.locator('button[aria-label^="Aspect Ratio"]').click()
await asyncio.sleep(0.5)

# Click option
options = page.locator('div[role="menuitem"]')
n = await options.count()
for i in range(n):
    text = (await options.nth(i).text_content() or "").strip()
    if text.startswith(value):  # "16:9\nWidescreen" startswith "16:9"
        await options.nth(i).click()
        return
```

### `set_video_resolution(value)` ("480p" or "720p")
Click radio in resolution group.

```python
group = page.locator('div[aria-label="Video resolution"]')
radios = group.locator('button[role="radio"]')
idx = 0 if value == "480p" else 1
await radios.nth(idx).click()
```

### `set_video_duration(value)` ("6s" or "10s")
```python
group = page.locator('div[aria-label="Video duration"]')
radios = group.locator('button[role="radio"]')
idx = 0 if value == "6s" else 1
await radios.nth(idx).click()
```

### `upload_ref(image_path)`
Click Upload, fire file input event.

```python
async with page.expect_file_chooser() as fc_info:
    await page.locator('button[aria-label^="Upload"]').click()
file_chooser = await fc_info.value
await file_chooser.set_files(str(image_path))
await asyncio.sleep(1.0)  # wait for upload preview
```

### `claude_pick_best(prompt_text)`
Capture masonry strip, call Claude Code CLI, return choice index.

```python
masonry = page.locator('[id^="imagine-masonry-section-"]').last
await masonry.scroll_into_view_if_needed()
await asyncio.sleep(0.5)

candidates_dir = Path(f"output/{project}/candidates/{counter:04d}")
candidates_dir.mkdir(parents=True, exist_ok=True)
strip_path = candidates_dir / "strip.png"
await masonry.screenshot(path=str(strip_path))

(candidates_dir / "prompt.txt").write_text(prompt_text, encoding='utf-8')

# Subprocess call
loop = asyncio.get_event_loop()
choice = await loop.run_in_executor(
    None, lambda: pick_best_image(strip_path, prompt_text)
)

# Save reason for debugging
if choice is not None:
    (candidates_dir / "pick.json").write_text(json.dumps({"choice": choice}))

return choice if choice is not None else 0  # fallback
```

### `wait_video_ready(timeout=300000)`
Poll for "Generating X%" overlay disappearance.

```python
start = time.time() * 1000
while (time.time() * 1000 - start) < timeout:
    # Find overlay with text matching pattern
    overlays = page.locator('div').filter(
        has_text=re.compile(r'^Generating\s+\d+%')
    )
    count = await overlays.count()
    
    if count == 0:
        return {"ok": True}
    
    # Optional: extract progress
    text = await overlays.first.text_content()
    match = re.search(r'(\d+)%', text or '')
    if match:
        log.info(f"Video progress: {match.group(1)}%")
    
    await asyncio.sleep(2)
return {"ok": False, "reason": "video_timeout"}
```

---

## Flow A — Text-to-Image (no reference, per-prompt loop)

**Use case**: Batch generate independent images, each prompt is a fresh chat.

```python
"text_to_image_no_ref": {
    "name": "Text-to-Image (no reference)",
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
        # Pick mode dispatch — runner picks based on config["pick_mode"]
        {"action": "pick_image", "save_to": "best_idx"},
        {"action": "click_image", "from_var": "best_idx"},
        {"action": "wait_url_match", "pattern": "/post/"},
        {"action": "download", "prefix": "pic"},
        {"action": "human_pause", "min_ms": 500, "max_ms": 1000},
        {"action": "click_back"},
        {"action": "wait_url_match", "pattern": "/imagine"},
    ],
}
```

---

## Flow B — Text-to-Image (single window, multi-prompt in one chat)

**Use case**: Sequence of related prompts where Grok uses previous image as context.

```python
"text_to_image_single_window": {
    "name": "Text-to-Image (single chat window)",
    "loop_per_prompt": False,  # internal loop
    "steps": [
        {"action": "ensure_at", "url": "/imagine"},
        {"action": "set_mode", "value": "image"},
        {"action": "set_quality", "value": "quality"},
        {"action": "set_aspect", "from_config": "aspect"},
        
        # First prompt — same as flow A up to download
        {"action": "fill_prompt", "from_prompt_index": 0},
        {"action": "click_submit"},
        {"action": "wait_image_ready"},
        {"action": "pick_image", "save_to": "best_idx"},
        {"action": "click_image", "from_var": "best_idx"},
        {"action": "wait_url_match", "pattern": "/post/"},
        {"action": "download", "prefix": "pic"},
        
        # Loop remaining prompts in same chat
        {"action": "loop_remaining_prompts", "steps": [
            {"action": "verify_input_empty"},
            {"action": "fill_prompt", "from_loop": "text"},
            {"action": "click_submit"},
            {"action": "wait_image_ready"},
            {"action": "pick_image", "save_to": "best_idx"},
            {"action": "click_image", "from_var": "best_idx"},
            {"action": "download", "prefix": "pic"},
        ]},
        
        {"action": "click_back"},
    ],
}
```

---

## Flow C — Image-to-Image

```python
"image_to_image": {
    "name": "Image-to-Image",
    "loop_per_prompt": True,
    "steps": [
        {"action": "ensure_at", "url": "/imagine"},
        {"action": "set_mode", "value": "image"},
        {"action": "set_quality", "value": "quality"},
        {"action": "upload_ref", "from_prompt": "ref_image"},
        {"action": "fill_prompt", "from_prompt": "text"},
        {"action": "click_submit"},
        {"action": "wait_image_ready"},
        {"action": "pick_image", "save_to": "best_idx"},
        {"action": "click_image", "from_var": "best_idx"},
        {"action": "wait_url_match", "pattern": "/post/"},
        {"action": "download", "prefix": "pic"},
        {"action": "click_back"},
    ],
}
```

---

## Flow D — Text-to-Video

**Note**: Video mode auto-pops result page after submit (no need to click result card).

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
        {"action": "wait_url_match", "pattern": "/post/"},  # auto-redirect
        {"action": "wait_video_ready"},
        {"action": "human_pause", "min_ms": 1000, "max_ms": 2000},
        {"action": "download", "prefix": "vid"},
        {"action": "click_back"},
    ],
}
```

---

## Flow E — Image-to-Video

```python
"image_to_video": {
    "name": "Image-to-Video (Make video from image)",
    "loop_per_prompt": True,
    "steps": [
        {"action": "ensure_at", "url": "/imagine"},
        {"action": "set_mode", "value": "video"},
        {"action": "set_video_resolution", "from_config": "resolution"},
        {"action": "set_video_duration", "from_config": "duration"},
        {"action": "set_aspect", "from_config": "aspect"},
        {"action": "upload_ref", "from_prompt": "ref_image"},
        {"action": "fill_prompt", "from_prompt": "text"},
        {"action": "click_submit"},
        {"action": "wait_url_match", "pattern": "/post/"},
        {"action": "wait_video_ready"},
        {"action": "download", "prefix": "vid"},
        {"action": "click_back"},
    ],
}
```

---

## Pick mode dispatch

The `pick_image` action delegates based on `config["pick_mode"]`:

```python
async def pick_image(self):
    mode = self.config.get("pick_mode", "auto")
    
    if mode == "auto":
        return 0  # Always first image
    
    elif mode == "claude":
        return await self.claude_pick_best()
    
    elif mode == "manual":
        # Future: dashboard server flow
        raise NotImplementedError("Manual pick deferred to v1.1")
    
    return 0  # Fallback
```

---

## Error handling matrix

| Error | Detection | Strategy | User-facing message |
|---|---|---|---|
| Rate limit | Toast `[data-sonner-toast]` text matches `/rate limit\|too many\|quota/i` | Wait 60s, retry. If 3x fail → pause session | "Rate limit hit. Waiting 60s before retry..." |
| Policy fail | Toast text matches `/violat\|policy\|inappropriate/i` | Log, skip prompt, continue | "Prompt #N skipped (policy)" |
| No masonry created in 60s | `wait_image_ready` timeout | Retry once, then skip | "Prompt #N timeout. Skipping." |
| Video stuck (no progress 5min) | `wait_video_ready` timeout | Click "Cancel Video" if exists, skip | "Video #N timed out. Skipping." |
| Patchright disconnect | Exception on any page action | Reconnect to CDP, retry from current step | "Browser disconnected. Reconnecting..." |
| Element not found | `wait_for_selector` timeout 10s | Take debug screenshot, log selector, skip | "UI changed? Selector failed: ..." |
| File download fail | `expect_download` timeout | Retry once | "Download failed for prompt #N" |

**Session-level state machine:**

```
RUNNING → (rate limit 3x) → PAUSED (manual resume)
RUNNING → (policy fail) → RUNNING (skip prompt)
RUNNING → (timeout) → RUNNING (skip prompt)
RUNNING → (user click Stop) → STOPPING → STOPPED (after current prompt done)
RUNNING → (browser disconnect) → RECONNECTING → RUNNING
```

---

## State persistence

`runner.state` dict (in-memory during session):

```python
{
    "counter": 5,                    # current prompt index (1-based for filenames)
    "current_prompt": {              # active prompt object
        "id": 5,
        "text": "a wolf howling",
        "ref_image": "wolf.jpg"      # optional
    },
    "vars": {                        # action save_to results
        "best_idx": 2
    },
    "errors": [                      # accumulated this session
        {"prompt_id": 3, "type": "policy_fail", "msg": "..."}
    ],
    "started_at": 1735234567,
    "downloaded_count": 4
}
```

Optional: persist to `output/{project}/.session.json` after each prompt for crash recovery (defer to v1.1).
