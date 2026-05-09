# Fast Mode — Spec & Implementation Guide (v2 — simplified 2026-05-09)

**Mục tiêu:** Cho phép re-gen nhanh hơn cho 1 scene cụ thể bằng cách bỏ qua "human typing" và dán prompt thẳng vào input Grok.

**Phạm vi:** Per-scene, **transient** (chỉ sống trong UI session). Không persist vào `scenes_edited.json` hay `state.json`. Reload project = mặc định OFF.

**Không trong scope:**
- KHÔNG scale timeout.
- KHÔNG đổi human-pause khác trong flow.
- KHÔNG đụng voice / render / export — chỉ gen image / image-with-refs / video.
- **KHÔNG hỗ trợ batch.** Batch luôn dùng `human_type` như cũ (xem §0).
- **KHÔNG có checkbox trên scene_row.** Fast mode chỉ tick trong `PreviewDialog` (xem §0).

---

## 0. Quyết định thiết kế (chốt 2026-05-09)

| Câu hỏi | Quyết định |
|---|---|
| Tick fast_mode ở đâu? | Chỉ trong `PreviewDialog` (header gần Save / Gen). Bỏ checkbox trên `scene_row`. |
| Batch có fast_mode? | Không. Chỉ single re-gen (`SingleImageWorker`, `SingleVideoWorker`) mới đọc fast_mode. |
| Sync dialog ↔ row | Không cần. Dialog có local state, đẩy vào signal payload khi click Gen. |
| Stop trong 5s sleep cuối | Có — chia thành 5 lần `await asyncio.sleep(1)` xen `_check_stop()`. |

→ Touch points giảm từ 11 file (spec v1) xuống **8 file** (xem §2). Bỏ hẳn `scene_row.py`, `batch_image.py`, `batch_video.py`.

---

## 1. Hành vi khi `fast_mode = True`

Thay vì `human_type` (per-keystroke 15-60ms + Shift+Enter cho `\n` + post-typing pause), `fill_prompt` làm:

1. Click input để focus.
2. `Ctrl+A` + `Delete` để clear.
3. Cho từng dòng (tách bởi `\n`):
   - `await page.keyboard.insert_text(line)` — paste tức thì, không per-char.
   - `Shift+Enter` giữa các dòng (không phải dòng cuối).
4. Sleep 5s **có check stop** (5 vòng × 1s, mỗi vòng `_check_stop()`).

> **Kỹ thuật:** input của Grok là TipTap (contenteditable, không phải `<input>`/`<textarea>`). `locator.fill()` của Playwright **không hoạt động** với TipTap — phải dùng `keyboard.insert_text()` qua focused element.

---

## 2. Touch points (8 file)

### 2.1 `engines/grok/actions.py`

`fill_prompt` thêm 2 param: `fast_mode: bool = False` + `stop_event: asyncio.Event | None = None`:

```python
async def fill_prompt(page: Page, text: str, speed: str = "fast",
                      fast_mode: bool = False,
                      stop_event: asyncio.Event | None = None) -> dict[str, Any]:
    try:
        if fast_mode:
            await _fast_paste_prompt(page, text, stop_event=stop_event)
        else:
            await human_type(page, SEL.PROMPT_INPUT, text, speed=speed)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"fill_prompt: {e}"}


async def _fast_paste_prompt(page: Page, text: str,
                              stop_event: asyncio.Event | None = None) -> None:
    await page.locator(SEL.PROMPT_INPUT).first.click()
    await asyncio.sleep(0.3)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.1)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            await page.keyboard.insert_text(line)
        if i < len(lines) - 1:
            await page.keyboard.press("Shift+Enter")
    # 5s settle, check stop_event mỗi giây.
    for _ in range(5):
        if stop_event is not None and stop_event.is_set():
            raise asyncio.CancelledError("stop requested during fast_paste settle")
        await asyncio.sleep(1)
```

> Lý do truyền `stop_event` thay vì gọi free helper `_check_stop()`:
> `actions.py` không có module-level stop helper — `_check_stop` hiện chỉ là method của
> `GrokImageRefEngine`. Để không bắt buộc tất cả action chuyển sang OOP, ta pass event
> qua param. Chỉ `_fast_paste_prompt` cần (action khác không có long sleep).

### 2.2 `engines/grok/runner.py`

Tại nhánh xử lý `fill_prompt` (line ~124):

```python
if action == "fill_prompt":
    speed = self.config.get("typing_speed", "fast")
    fast_mode = bool(self.config.get("fast_mode", False))
    stop_event = self.config.get("stop_event")  # asyncio.Event | None
    return await actions.fill_prompt(
        page, self._resolved_value(step),
        speed=speed, fast_mode=fast_mode, stop_event=stop_event,
    )
```

### 2.3 `engines/grok/engine.py`

Cả `GrokImageEngine.gen_image` và `GrokVideoEngine.gen_video`: bơm `fast_mode` + `stop_event` từ `settings` vào `config` truyền cho `FlowRunner`.

```python
config = {
    ...,
    "fast_mode": bool(settings.get("fast_mode", False)),
    "stop_event": settings.get("stop_event"),  # asyncio.Event | None
}
```

Cập nhật docstring settings dict liệt kê `fast_mode: bool (default False)` và `stop_event: asyncio.Event | None (default None)`.

### 2.4 `engines/grok/image_ref_engine.py`

`gen_image_with_refs` thêm param `fast_mode: bool = False`. Truyền cả `fast_mode` lẫn
`self._stop_event` (đã có sẵn) vào `A.fill_prompt`:

```python
async def gen_image_with_refs(self, *, scene_id, prompt, ref_paths,
                              output_path, aspect, fast_mode: bool = False):
    ...
    r = await A.fill_prompt(
        self.page, prompt,
        fast_mode=fast_mode, stop_event=self._stop_event,
    )
```

### 2.5 `ui/dialogs/preview_dialog.py`

**Đổi signal payload** (thêm `bool` vào hai signal hiện có):

```python
gen_image_requested = pyqtSignal(str, bool)       # scene_id, fast_mode
gen_animation_requested = pyqtSignal(str, bool)   # scene_id, fast_mode
```

**Thêm checkbox** — đặt trong `btns` row (`_build_ui`), trước `b_save`, hoặc song song với `b_open`:

```python
self.fast_check = QCheckBox("⚡ Fast")
self.fast_check.setToolTip(
    "Fast mode: paste prompt thẳng + đợi 5s thay vì gõ từng ký tự.\n"
    "Chỉ áp dụng cho lần Gen này, không persist."
)
btns.addWidget(self.fast_check)
```

**Đổi 2 handler emit signal** truyền thêm fast_mode:

```python
def _on_gen_image(self) -> None:
    self.save_requested.emit(self.scene.id, self._collect_updates())
    self.gen_image_requested.emit(self.scene.id, self.fast_check.isChecked())
    self.accept()

def _on_gen_animation(self) -> None:
    self.save_requested.emit(self.scene.id, self._collect_updates())
    self.gen_animation_requested.emit(self.scene.id, self.fast_check.isChecked())
    self.accept()
```

> Dialog không cần `__init__` param `fast_mode` — checkbox khởi tạo OFF mỗi lần mở (transient theo session UI; user có thể tick lại nếu muốn).

### 2.6 `ui/main_window.py`

Wire 2 signal mới (cập nhật chữ ký lambda/handler):

```python
dialog.gen_image_requested.connect(
    lambda sid, fast: self._regen_one(sid, fast_mode=fast)
)
dialog.gen_animation_requested.connect(
    lambda sid, fast: self._regen_one_video(sid, fast_mode=fast)
)
```

`_regen_one` và `_regen_one_video` thêm kwarg `fast_mode: bool = False` rồi truyền vào constructor worker.

### 2.7 `workers/single_image.py`

`__init__` thêm `fast_mode: bool = False`. Trong `_async_run`:

- **Engine path** (`gen_image`): trước khi gọi engine,
  ```python
  settings["fast_mode"] = self.fast_mode
  settings["stop_event"] = self.stop_event
  ```
- **Ref path** (`gen_image_with_refs`):
  ```python
  ref_engine.set_stop_event(self.stop_event)  # nếu chưa gọi
  await ref_engine.gen_image_with_refs(..., fast_mode=self.fast_mode)
  ```
  (`fast_mode` qua kwarg, `stop_event` qua `set_stop_event` đã có sẵn.)

### 2.8 `workers/single_video.py`

Tương tự 2.7: `__init__` thêm `fast_mode: bool = False`. Trước `engine.gen_video`:
```python
settings["fast_mode"] = self.fast_mode
settings["stop_event"] = self.stop_event
```
Slideshow nhánh **không** dùng fast_mode (không có Grok).

---

## 3. KHÔNG đụng

- `core/schema.py`, `core/project.py`, `scenes_edited.json`, `state.json` — không thêm field nào.
- `ui/scene_row.py` — không có checkbox ⚡.
- `workers/batch_image.py`, `workers/batch_video.py` — batch luôn `fast_mode=False`.
- Timeout literal trong `actions.py` — giữ nguyên 100%.
- `voice/`, `render/`, `slideshow/` — không liên quan.

---

## 4. Checklist resume (theo thứ tự đề xuất)

- [ ] **Step 1** — `actions.py`: thêm `_fast_paste_prompt(page, text, stop_event)` + param `fast_mode` + `stop_event` cho `fill_prompt`. Verify 5s settle dùng `for _ in range(5)` + check stop_event.
- [ ] **Step 2** — `runner.py`: đọc `config["fast_mode"]` + `config["stop_event"]` → truyền xuống `actions.fill_prompt`.
- [ ] **Step 3** — `engine.py` (Image + Video): bơm `fast_mode` + `stop_event` từ `settings` vào `config`.
- [ ] **Step 4** — `image_ref_engine.py`: param `fast_mode` + truyền vào `A.fill_prompt(..., fast_mode=..., stop_event=self._stop_event)`.
- [ ] **Step 5** — `preview_dialog.py`: thêm checkbox `⚡ Fast` + đổi signal payload `(str, bool)`. Update 2 handler `_on_gen_image` / `_on_gen_animation`.
- [ ] **Step 6** — `main_window.py`: wire signal mới, `_regen_one*` nhận `fast_mode`, truyền vào worker constructor.
- [ ] **Step 7** — `single_image.py` + `single_video.py`: `__init__` nhận `fast_mode`, bơm `settings["fast_mode"]` + `settings["stop_event"]` vào engine call. Ref path: gọi `set_stop_event` + `gen_image_with_refs(fast_mode=...)`.
- [ ] **Step 8** — Smoke test:
  - [ ] Mở dialog 1 scene → tick ⚡ → Gen Image (no refs) → prompt paste tức thì, đợi 5s, ảnh ra OK.
  - [ ] Tick ⚡ → Gen Image (có refs) → cùng hành vi, đi qua `image_ref_engine`.
  - [ ] Tick ⚡ → Gen Video (video_grok) → OK; Gen Video (slideshow) → fast_mode bị bỏ qua, slideshow render bình thường.
  - [ ] Untick → human_type chạy như cũ, không regression.
  - [ ] Mở lại dialog → checkbox reset OFF (transient).
  - [ ] Bấm Stop trong lúc 5s sleep cuối → worker thoát ≤ 1s.
  - [ ] Batch ảnh / batch video → log không thấy `fast paste`, vẫn human_type (xác nhận batch ignore fast).

---

## 5. Ghi chú edge case

- **Prompt rỗng**: `_fast_paste_prompt` skip `insert_text` cho line rỗng. Vẫn ngủ 5s — không khác `human_type` trên prompt rỗng.
- **Prompt nhiều dòng**: TipTap nhận `Shift+Enter` thành soft break. `insert_text` không tự xử `\n` → bắt buộc tách thủ công.
- **Clipboard permission**: `keyboard.insert_text` không cần clipboard — đi qua textInput event. Không phải Ctrl+V.
- **Slideshow visual_type**: nhánh slideshow không gọi Grok → `fast_mode` không có hiệu lực, không cần raise lỗi.
- **Stop trong 5s sleep cuối**: pattern `for _ in range(5): _check_stop(); await asyncio.sleep(1)` — đã consistent với retry/cancel logic update 2026-05-09.
