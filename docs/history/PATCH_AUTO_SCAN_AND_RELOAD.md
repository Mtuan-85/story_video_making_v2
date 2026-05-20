# Patch — Auto-scan Sources + UI Rename + Reload Pipeline

> **Goal**: Fix 3 vấn đề urgent sau Patch A + B đã apply.
> **Effort**: ~2-2.5h
> **Scope**: 5 files modify (paths, project, scene_row, preview_dialog, main_window).
> **NOT in scope**: Kdenlive multi-voice/BGM (defer Sprint sau), project file convention (Patch B đã handle).

---

## Vấn đề bro đang gặp

### Vấn đề 1: Source file đổi tên → app không nhận

```
sources/
├── scene_39.jpg   ← user rename từ pic39.jpg
└── scene_39.mp4   ← user rename từ vid39.mp4
```

App **vẫn** check `pic39.jpg` / `vid39.mp4` → file đã có nhưng không match → status missing.

→ Click 🎬 trên SCENE-39 → popup "chưa có ảnh ready để làm I2V" (mặc dù `scene_39.jpg` tồn tại).

### Vấn đề 2: UI button confusing trong PreviewDialog

Hiện tại (3 buttons):
```
[💾 Save]  [🖼 Save & Gen Image]  [🎞 Save & Gen Animation]  [📁 Folder]
```

Bro muốn rename:
```
[💾 Save]  [🖼 Gen Image]  [🎞 Gen Video]  [📁 Folder]
```

Logic giữ nguyên — Gen vẫn save prompt trước. Chỉ đổi label cho rõ ràng.

### Vấn đề 3: Reload không refresh sources

User edit sources/ ngoài app → click Reload → thumbnail cũ vẫn hiện, status không update.

→ Reload pipeline thiếu invalidate cache + re-scan sources.

---

## Strategy

### Naming convention: Auto-scan multi-pattern (không thêm field JSON)

Per bro chốt Q1=B:
> "Tôi có thể đảm bảo trong sources chuẩn. Nếu ko load đc thì notification là xong sẽ đỡ tốn công code hơn."

→ App tự thử nhiều pattern:

```python
# Image patterns (tried in order, first match wins):
1. pic{N}.{ext}           # pic39.jpg, pic39.png
2. pic{N:02d}.{ext}        # pic39.jpg (cùng số nhưng zero-pad nếu N<10)
3. scene_{N}.{ext}         # scene_39.jpg
4. scene_{N:02d}.{ext}     # scene_39.jpg (cùng số nhưng zero-pad)

Extensions: .jpg, .jpeg, .png, .webp
```

```python
# Video patterns:
1. vid{N}.{ext}
2. vid{N:02d}.{ext}
3. scene_{N}.{ext}
4. scene_{N:02d}.{ext}

Extensions: .mp4, .mov, .webm
```

→ Nếu không match → notification, không crash.

→ User vẫn có thể dùng convention cũ (`pic39.jpg`) hoặc convention mới (`scene_39.jpg`) — cả 2 đều work.

---

## Files cần modify

| File | Change | Effort |
|---|---|---|
| `core/paths.py` | Add `find_image(N)` / `find_video(N)` multi-pattern; deprecate hardcode `image_path` / `video_path` (giữ làm fallback writers) | 30 phút |
| `core/project.py` | Reload pipeline: re-read scenes + scan sources + reconcile status; expose `reload()` method | 30 phút |
| `ui/scene_row.py` | Use `find_image` / `find_video` thay vì hardcode path; thumbnail invalidate on reload | 30 phút |
| `ui/dialogs/preview_dialog.py` | Rename buttons "Save & Gen X" → "Gen X" | 10 phút |
| `ui/main_window.py` | Reload button trigger full pipeline + show notification dialog cho missing files | 30 phút |

**Total: ~2-2.5h**

---

## CHANGE 1: `core/paths.py` — Auto-scan with multi-pattern

### Add 2 new methods

```python
class ProjectPaths:
    # ... existing fields ...
    
    # Image patterns: pic{N}, pic{N:02d}, scene_{N}, scene_{N:02d}
    _IMAGE_PATTERNS = [
        "pic{n}",
        "pic{n:02d}",
        "scene_{n}",
        "scene_{n:02d}",
    ]
    _IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]
    
    # Video patterns
    _VIDEO_PATTERNS = [
        "vid{n}",
        "vid{n:02d}",
        "scene_{n}",
        "scene_{n:02d}",
    ]
    _VIDEO_EXTS = [".mp4", ".mov", ".webm"]
    
    @property
    def sources_dir(self) -> Path:
        return self.root / "sources"
    
    def find_image(self, scene_idx: int) -> Path | None:
        """Find image file cho scene_idx với multi-pattern match.
        
        Patterns: pic{N}, pic{N:02d}, scene_{N}, scene_{N:02d}
        Extensions: .jpg, .jpeg, .png, .webp
        First match wins.
        
        Returns None nếu không tìm thấy.
        """
        sources = self.sources_dir
        if not sources.exists():
            return None
        
        for pattern in self._IMAGE_PATTERNS:
            stem = pattern.format(n=scene_idx)
            for ext in self._IMAGE_EXTS:
                candidate = sources / f"{stem}{ext}"
                if candidate.exists():
                    return candidate
        
        return None
    
    def find_video(self, scene_idx: int) -> Path | None:
        """Same logic cho video files."""
        sources = self.sources_dir
        if not sources.exists():
            return None
        
        for pattern in self._VIDEO_PATTERNS:
            stem = pattern.format(n=scene_idx)
            for ext in self._VIDEO_EXTS:
                candidate = sources / f"{stem}{ext}"
                if candidate.exists():
                    return candidate
        
        return None
    
    def scan_sources(self) -> dict:
        """Scan sources/ folder, return all matched scene files.
        
        Useful cho reload pipeline + missing file notification.
        
        Returns:
            {
                "matched": {scene_idx: {"image": Path, "video": Path or None}},
                "orphan": [Path, ...],  # files in sources/ không match scene nào
            }
        """
        sources = self.sources_dir
        result = {"matched": {}, "orphan": []}
        
        if not sources.exists():
            return result
        
        all_files = [f for f in sources.iterdir() if f.is_file()]
        
        # For each potential scene_idx (1 to 200, generous upper bound)
        # check if any pattern matches.
        # NOTE: caller passes max_scenes from project.scenes_count
        # → in scan_sources signature, accept max_scenes param.
        # Implementation simplified here — see project.py reload() for use.
        
        return result
```

### Keep existing API for writers

Writers (Grok engine save image, slideshow render save video) vẫn cần **deterministic path** để ghi file.

→ Giữ nguyên `image_path(N)` / `video_path(N)` returning `pic{N}.jpg` / `vid{N}.mp4` (default convention) cho writers.

→ Readers (UI display, render composite, voice align) dùng `find_image(N)` / `find_video(N)` để tolerate user-renamed files.

```python
def image_path(self, scene_idx: int, ext: str = "jpg") -> Path:
    """Default WRITE path — pic{N}.{ext}. Use cho engines/writers.
    
    Readers nên dùng find_image() để tolerate renames.
    """
    return self.sources_dir / f"pic{scene_idx}.{ext}"


def video_path(self, scene_idx: int, ext: str = "mp4") -> Path:
    """Default WRITE path — vid{N}.{ext}."""
    return self.sources_dir / f"vid{scene_idx}.{ext}"
```

---

## CHANGE 2: `core/project.py` — Reload pipeline

### Add `reload()` method

```python
class Project:
    # ... existing __init__, load, save ...
    
    def reload(self) -> dict:
        """Full reload pipeline:
        1. Re-read scenes_edited.json (fresh from disk)
        2. Re-read state JSON
        3. Scan sources/ với multi-pattern
        4. Reconcile: update each scene's image/video status
        5. Return summary cho UI display
        
        Returns:
            {
                "scenes_count": int,
                "images_found": int,
                "videos_found": int,
                "missing": [{"scene_id": str, "missing": ["image"|"video"]}],
                "orphans": [str],  # filenames không match scene nào
            }
        """
        from loguru import logger as log
        
        # 1. Re-read scenes
        log.info("Reload: re-reading scenes from disk...")
        self.scenes_json = self._load_scenes()  # existing method
        
        # 2. Re-read state
        if self.paths.state_json.exists():
            self.state = self._load_state()
        
        # 3+4. Scan sources, reconcile
        scenes_count = len(self.scenes_json.scenes)
        images_found = 0
        videos_found = 0
        missing = []
        
        # Track which files matched (for orphan detection)
        matched_files: set[Path] = set()
        
        for i, scene in enumerate(self.scenes_json.scenes, start=1):
            img = self.paths.find_image(i)
            vid = self.paths.find_video(i)
            
            if img:
                images_found += 1
                matched_files.add(img)
            
            if vid:
                videos_found += 1
                matched_files.add(vid)
            
            # Track missing per scene
            scene_missing = []
            if not img:
                scene_missing.append("image")
            # Video chỉ flag missing nếu visual_type cần video
            if not vid and scene.visual_type in ("video_grok", "slideshow", "ken_burns_self", "ken_burns_cont"):
                scene_missing.append("video")
            
            if scene_missing:
                missing.append({
                    "scene_id": scene.id,
                    "scene_idx": i,
                    "missing": scene_missing,
                })
        
        # Find orphans: files in sources/ không match scene nào
        orphans = []
        if self.paths.sources_dir.exists():
            all_files = [
                f for f in self.paths.sources_dir.iterdir()
                if f.is_file() and f not in matched_files
            ]
            orphans = [f.name for f in all_files]
        
        summary = {
            "scenes_count": scenes_count,
            "images_found": images_found,
            "videos_found": videos_found,
            "missing": missing,
            "orphans": orphans,
        }
        
        log.info(
            f"Reload done: {scenes_count} scenes, "
            f"{images_found} images, {videos_found} videos, "
            f"{len(missing)} missing, {len(orphans)} orphans"
        )
        return summary
```

---

## CHANGE 3: `ui/scene_row.py` — Use `find_image` / `find_video` + invalidate thumbnail

### Replace hardcode path

Tìm chỗ check image/video tồn tại:

```python
# CŨ:
img_path = self.project.paths.image_path(self.scene_idx)
if img_path.exists():
    # show thumbnail

# MỚI:
img_path = self.project.paths.find_image(self.scene_idx)
if img_path is not None:
    # show thumbnail
```

→ Tương tự cho video.

### Thumbnail cache invalidation

Khi reload, scene row cần regenerate thumbnail từ file path mới (không dùng QPixmap cache cũ).

```python
def refresh_thumbnail(self):
    """Re-load thumbnail from disk, bypass QPixmap cache."""
    img_path = self.project.paths.find_image(self.scene_idx)
    
    if img_path is None:
        # Show placeholder
        self.thumb_label.setPixmap(self._placeholder_pixmap())
        return
    
    # CRITICAL: load with cacheKey timestamp để bypass internal cache
    pixmap = QPixmap()
    pixmap.load(str(img_path))  # fresh load, not cached
    
    if pixmap.isNull():
        log.warning(f"Failed to load thumbnail: {img_path}")
        self.thumb_label.setPixmap(self._placeholder_pixmap())
        return
    
    # Scale + display
    scaled = pixmap.scaled(
        self.thumb_size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    self.thumb_label.setPixmap(scaled)


def update_status(self):
    """Re-evaluate has_image, has_video, refresh icons."""
    has_img = self.project.paths.find_image(self.scene_idx) is not None
    has_vid = self.project.paths.find_video(self.scene_idx) is not None
    
    self.image_status_icon.setVisible(has_img)
    self.video_status_icon.setVisible(has_vid)
    
    # Update button tooltips theo status (đã có từ Patch A)
    self._apply_asset()
```

### Add slot listening for reload signal

```python
def on_project_reloaded(self):
    """Slot called when MainWindow emits project_reloaded signal."""
    self.refresh_thumbnail()
    self.update_status()
```

---

## CHANGE 4: `ui/dialogs/preview_dialog.py` — Rename buttons

### Find current button setup

```python
# CŨ:
self.btn_save = QPushButton("💾 Save")
self.btn_gen_image = QPushButton("🖼 Save & Gen Image")
self.btn_gen_animation = QPushButton("🎞 Save & Gen Animation")
```

### Replace với

```python
# MỚI:
self.btn_save = QPushButton("💾 Save")
self.btn_gen_image = QPushButton("🖼 Gen Image")
self.btn_gen_animation = QPushButton("🎞 Gen Video")
# (Logic không đổi — Gen vẫn save trước, chỉ đổi label)
```

→ Image 1 (bro upload) screenshot dùng "Save & Gen Image" / "Save & Gen Animation". Sau patch sẽ là "Gen Image" / "Gen Video".

→ Tooltip giúp user hiểu vẫn save:

```python
self.btn_gen_image.setToolTip(
    "Save prompt + Generate image (overwrite existing)"
)
self.btn_gen_animation.setToolTip(
    "Save prompt + Generate video (requires existing image for I2V)"
)
```

### Verify button reference

```python
# Action handler signal name không đổi — chỉ button text đổi:
self.btn_gen_image.clicked.connect(self._on_gen_image)
self.btn_gen_animation.clicked.connect(self._on_gen_animation)


def _on_gen_image(self):
    self._save_prompt()           # save first
    self.gen_image_requested.emit()  # signal to MainWindow
    self.accept()


def _on_gen_animation(self):
    # Pre-check: dùng find_image (multi-pattern) thay vì hardcode
    img = self.project.paths.find_image(self.scene_idx)
    if img is None:
        QMessageBox.warning(
            self,
            f"Không đủ điều kiện — {self.scene_id}",
            "chưa có ảnh ready để làm I2V"
        )
        return
    
    self._save_prompt()
    self.gen_animation_requested.emit()
    self.accept()
```

→ **Bug Vấn đề 3 (image 3)** fix ở đây: thay `image_path(N).exists()` → `find_image(N) is not None`.

---

## CHANGE 5: `ui/main_window.py` — Reload pipeline + notification

### Reload button handler

```python
def _on_reload_project(self):
    """Trigger full reload pipeline + show summary dialog."""
    if not self.project:
        QMessageBox.information(self, "Reload", "Chưa load project nào.")
        return
    
    log.info("User triggered reload")
    
    try:
        summary = self.project.reload()
    except Exception as e:
        log.error(f"Reload failed: {e}")
        QMessageBox.critical(self, "Reload failed", str(e))
        return
    
    # Emit signal cho all scene rows refresh
    self.project_reloaded.emit()
    
    # Build notification message
    self._show_reload_summary(summary)


def _show_reload_summary(self, summary: dict):
    """Show notification dialog với summary từ reload."""
    scenes_count = summary["scenes_count"]
    images_found = summary["images_found"]
    videos_found = summary["videos_found"]
    missing = summary["missing"]
    orphans = summary["orphans"]
    
    msg_lines = [
        f"<b>Reload xong</b>",
        f"",
        f"📋 Scenes: {scenes_count}",
        f"🖼 Images found: {images_found}/{scenes_count}",
        f"🎞 Videos found: {videos_found} (chỉ scenes cần video)",
    ]
    
    if missing:
        msg_lines.append("")
        msg_lines.append(f"<b>⚠ Missing files ({len(missing)} scenes):</b>")
        # Show first 10 missing
        for item in missing[:10]:
            scene_id = item["scene_id"]
            missing_types = ", ".join(item["missing"])
            msg_lines.append(f"  • {scene_id}: thiếu {missing_types}")
        if len(missing) > 10:
            msg_lines.append(f"  ... và {len(missing) - 10} scenes khác")
        msg_lines.append("")
        msg_lines.append(
            "<i>Thử rename file theo pattern: "
            "pic{N}.jpg, scene_{N}.jpg, pic{N:02d}.jpg, scene_{N:02d}.jpg</i>"
        )
    
    if orphans:
        msg_lines.append("")
        msg_lines.append(f"<b>📂 Orphan files ({len(orphans)}):</b>")
        msg_lines.append(
            "<i>Files trong sources/ không match scene nào:</i>"
        )
        for name in orphans[:5]:
            msg_lines.append(f"  • {name}")
        if len(orphans) > 5:
            msg_lines.append(f"  ... và {len(orphans) - 5} files khác")
    
    if not missing and not orphans:
        msg_lines.append("")
        msg_lines.append("<b style='color:#2e7d32'>✓ All sources matched cleanly</b>")
    
    msg_html = "<br>".join(msg_lines)
    
    box = QMessageBox(self)
    box.setWindowTitle("Reload — Summary")
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(msg_html)
    box.setIcon(QMessageBox.Icon.Information if not missing else QMessageBox.Icon.Warning)
    box.exec()
```

### Add reload signal

```python
class MainWindow(QMainWindow):
    project_reloaded = pyqtSignal()  # NEW signal
    
    def __init__(self):
        # ... existing setup ...
        self.project_reloaded.connect(self._on_project_reloaded_internal)
    
    def _on_project_reloaded_internal(self):
        """Forward reload to scene list to refresh all rows."""
        if self.scene_list:
            self.scene_list.refresh_all()  # SceneList propagates to rows
```

### Reload button placement

Verify nút reload đã tồn tại. Nếu chưa, add vào toolbar:

```python
btn_reload = QPushButton("🔄 Reload")
btn_reload.setToolTip("Re-read scenes + scan sources/")
btn_reload.clicked.connect(self._on_reload_project)
```

→ Hoặc dùng Patch B's "Reset to design" button — clarify với user xem nên dùng button nào.

→ **Recommend: 2 buttons riêng**:
- "🔄 Reload" — re-read + scan, KHÔNG động scenes_edited.json
- "↶ Reset to design" — overwrite scenes_edited.json từ scenes.json (đã có từ Patch B)

### `ui/scene_list.py` add refresh_all

```python
class SceneList(QWidget):
    def refresh_all(self):
        """Trigger refresh on all scene rows."""
        for row in self._rows:
            row.refresh_thumbnail()
            row.update_status()
```

---

## Test plan

### Test 1: Auto-scan — `scene_39.jpg` được nhận

```
1. Load project test_live (scenes.json có SCENE-39)
2. Manual: trong sources/, rename pic39.jpg → scene_39.jpg
3. Click 🔄 Reload
4. Verify:
   ✓ Notification: "scenes 63, images 63" (vẫn count đủ)
   ✓ Thumbnail SCENE-39 hiện đúng (load từ scene_39.jpg)
   ✓ Status icon "image ready" cho SCENE-39
```

### Test 2: Gen Video bug fix

```
1. SOURCES/ có scene_39.jpg + scene_39.mp4 (rename từ pic39, vid39)
2. Click 🔄 Reload
3. Click 🎬 trên SCENE-39 row → PreviewDialog mở
4. Click "🎞 Gen Video"
5. Verify:
   ✓ KHÔNG popup "chưa có ảnh ready"
   ✓ I2V flow start (uses scene_39.jpg as ref input)
```

### Test 3: UI button rename

```
1. Click 🖼 hoặc 🎬 trên scene row
2. PreviewDialog mở
3. Verify button labels:
   ✓ [💾 Save] (giữ)
   ✓ [🖼 Gen Image] (was: "Save & Gen Image")
   ✓ [🎞 Gen Video] (was: "Save & Gen Animation")
4. Click "Gen Image" → verify save prompt + trigger gen
5. Click "Gen Video" → verify save prompt + trigger gen (nếu có ảnh ready)
```

### Test 4: Missing file notification

```
1. SOURCES/ chỉ có file cho 50/63 scenes
2. Click 🔄 Reload
3. Verify notification dialog:
   ✓ Header: "Reload xong"
   ✓ Stats: scenes 63, images 50/63
   ✓ Missing list: 13 scenes liệt kê (first 10 + "... và 3 scenes khác")
   ✓ Pattern hint: "Thử rename: pic{N}.jpg, scene_{N}.jpg..."
```

### Test 5: Orphan file detection

```
1. SOURCES/ có random_file.jpg + pic1.jpg + pic2.jpg (chỉ 2 match scenes)
2. Reload
3. Verify notification:
   ✓ Orphans section list "random_file.jpg"
```

### Test 6: Reload thumbnail invalidation

```
1. SOURCES/pic5.jpg = ảnh A
2. Reload → SCENE-05 thumbnail hiện ảnh A
3. Manual overwrite: replace SOURCES/pic5.jpg với ảnh B (cùng tên file)
4. Click 🔄 Reload
5. Verify SCENE-05 thumbnail update sang ảnh B (KHÔNG dùng QPixmap cache cũ)
```

### Test 7: Backward compat — convention pic{N}.jpg vẫn work

```
1. SOURCES/ chỉ dùng convention cũ (pic1.jpg, vid1.mp4, ...)
2. Load project + Reload
3. Verify:
   ✓ All scenes match
   ✓ KHÔNG missing notification
   ✓ Thumbnails hiện đúng
```

---

## Build order

1. **Backup commit** trước khi modify (5 phút)
2. CHANGE 1: `core/paths.py` add `find_image` / `find_video` / `scan_sources` (30 phút)
3. CHANGE 2: `core/project.py` add `reload()` method (30 phút)
4. CHANGE 4: `ui/dialogs/preview_dialog.py` rename buttons + use `find_image` (15 phút)
5. CHANGE 3: `ui/scene_row.py` use `find_image` / `find_video` + thumbnail invalidate (30 phút)
6. CHANGE 5: `ui/main_window.py` reload handler + notification dialog (30 phút)
7. Test 1-7 (30 phút)
8. Commit "Sprint 3 patch: auto-scan sources + UI rename + reload pipeline"

**Total: ~2.5h**

---

## Confirm trước khi code

- [ ] Patch A + B đã commit trên `main` (verify `git log --oneline -5`)
- [ ] `core/paths.py` đã có Patch B (`scenes_edited`, `state_json` stem-based)
- [ ] `core/project.py::Project.load()` đã có Patch B (file API thay vì dir)
- [ ] `ui/dialogs/preview_dialog.py` đã có Patch A (buttons "Save & Gen X")
- [ ] Test data ready: project với scenes.json + một số file rename mix

---

## Defer to Sprint sau

KHÔNG fix trong patch này (per bro yêu cầu):
- ❌ Kdenlive multi-voice (chỉ lấy `voice_files[0]`)
- ❌ Kdenlive multi-BGM
- ❌ Kdenlive scene skip silent → log warning
- ❌ Kdenlive effects/transitions/colors export
- ❌ Verify Kdenlive software load file `.kdenlive` (chưa cài/test)

→ Defer to **Sprint 4 Kdenlive**.

→ Sau patch này pass test → đóng Sprint 3 → tag v0.3.0 → Sprint Kdenlive.
