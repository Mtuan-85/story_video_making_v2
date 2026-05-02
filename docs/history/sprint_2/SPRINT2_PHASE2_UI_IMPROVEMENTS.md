# Sprint 2 — Phase 2: UI Improvements + Visual/Effect Dropdowns

> **Priority**: Sau Phase 1 (voice-first) build và test xong.
> **Mục đích**: UX overhaul + control trực tiếp visual_type + effect ở mỗi scene row.

---

## Yêu cầu

### Scene Row mới — Layout cuối cùng

```
[☐] [thumb 60px] SCENE-01  [▾ image_grok]  [▾ zoom_in]  8s  [icons]  ✏
 │   │            │         │                │              │         │
 │   │            │         │                │              │         └─ Edit (mở Preview Dialog)
 │   │            │         │                │              └─ Status icons (image/video/voice ready states)
 │   │            │         │                └─ Duration label (read-only, just text "8s")
 │   │            │         └─ Effect dropdown (zoom_in / zoom_out / no_effect)
 │   │            └─ Visual type dropdown (image_grok / video_grok / slideshow_v4)
 │   └─ Scene ID
 └─ Single checkbox (bỏ tick 2)
[bỏ thumbnail click handler – click thumbnail = mở Preview Dialog]
```

### 1. Bỏ checkbox thứ 2

Hiện tại 2 checkbox đầu row → bỏ 1, chỉ giữ 1 (cho batch select).

### 2. Bỏ nút ⚠ + nút 🔄 ở cuối row

Chỉ giữ nút ✏ Edit (mở Preview Dialog).

### 3. Thumbnail 60px

- Cạnh dài nhất 60px
- Aspect 16:9 → 60×34, 9:16 → 34×60
- Cache: `test_run/thumbnails/SCENE-XX.jpg`
- Auto-generate sau khi gen ảnh/video xong
- Click thumbnail = mở Preview Dialog
- Nếu chưa có thumbnail: hiển thị placeholder "?"

### 4. Visual type dropdown trong row

3 options:
- `image_grok` — ảnh tĩnh từ Grok
- `video_grok` — video i2v từ Grok
- `slideshow_v4` — slideshow animation

→ User đổi = auto save scenes.json (atomic).

### 5. Effect dropdown trong row

3 options:
- `zoom_in` — Ken Burns zoom in 1.0 → 1.2
- `zoom_out` — Ken Burns zoom out 1.2 → 1.0
- `no_effect` — không zoom (visual hiển thị nguyên)

→ User đổi = auto save scenes.json.

### 6. Duration label

Read-only, chỉ hiện `{duration}s`. Edit qua Preview Dialog.

### 7. Auto-fill default values khi load scenes.json

Khi load scenes.json mà KHÔNG có field `effect`:

```python
def auto_fill_effects(scenes):
    """Auto-fill effect field if missing. Save back to scenes.json."""
    
    # Counter cho alternate (chỉ count scenes cần alternate)
    alternate_idx = 0
    changed = False
    
    for scene in scenes:
        if hasattr(scene, "effect") and scene.effect is not None:
            continue  # đã có, skip
        
        if scene.visual_type == "video_grok":
            scene.effect = "no_effect"  # default cho video
        elif scene.visual_type in ("image_grok", "slideshow_v4"):
            scene.effect = "zoom_in" if alternate_idx % 2 == 0 else "zoom_out"
            alternate_idx += 1
        else:
            scene.effect = "no_effect"
        
        changed = True
    
    return changed
```

→ Sau auto-fill, save scenes.json (nếu có thay đổi).

### 8. Preview Dialog với prompt edit + VLC

Click thumbnail HOẶC click ✏ → mở Preview Dialog:
- Visual lớn (image static / video VLC embed)
- Story textarea
- ImagePrompt textarea
- VideoPrompt textarea (optional)
- Visual type dropdown (sync với row)
- Effect dropdown (sync với row)
- Duration spinbox
- [Save] [Re-gen] [Open folder] [Đóng]

### 9. Effect apply ONLY khi render final

```
Scene workflow:
- Preview ảnh/video: KHÔNG apply effect (xem ảnh/video original)
- Re-gen: KHÔNG apply effect
- Render final: APPLY effect zoom + fade + duration_adjusted (Phase 1)
```

### 10. Batch video dispatch theo visual_type

Click "Batch video" → cho mỗi scene selected:
- `image_grok` → SKIP (giữ ảnh, không tạo video)
- `video_grok` → Gen video Grok i2v
- `slideshow_v4` → Render slideshow

→ KHÔNG cần dropdown ở button "Batch video". Chỉ là button đơn giản, dispatch theo visual_type của từng scene.

---

## Implementation

### 1. Schema update

`core/schema.py` — thêm field `effect`:

```python
from typing import Literal

VisualType = Literal["image_grok", "video_grok", "slideshow_v4"]
EffectType = Literal["zoom_in", "zoom_out", "no_effect"]

class Scene(BaseModel):
    id: str
    visual_type: VisualType
    effect: EffectType = "no_effect"  # default; auto-fill khi load nếu thiếu
    duration: int
    story_en: str
    imagePrompt: str
    videoPrompt: Optional[str] = None
```

→ Bỏ `ken_burns_self` khỏi VisualType enum.

### 2. Auto-fill effects khi load project

`core/project.py` — trong `Project.load()`:

```python
@classmethod
def load(cls, project_dir: Path) -> "Project":
    # ... existing load logic
    
    # Auto-fill default effect for scenes missing it
    changed = _auto_fill_effects(scenes_json.scenes)
    
    project = cls(paths, scenes_json, state, voice_mapping)
    
    # If auto-fill changed scenes, save back
    if changed:
        project._save_scenes_json_atomic()
        log.info("Auto-filled missing effect fields, saved scenes.json")
    
    return project


def _auto_fill_effects(scenes: list) -> bool:
    """Auto-fill effect field if missing. Returns True if changed."""
    alternate_idx = 0
    changed = False
    
    for scene in scenes:
        if scene.effect is not None and scene.effect != "":
            continue
        
        if scene.visual_type == "video_grok":
            scene.effect = "no_effect"
        elif scene.visual_type in ("image_grok", "slideshow_v4"):
            scene.effect = "zoom_in" if alternate_idx % 2 == 0 else "zoom_out"
            alternate_idx += 1
        else:
            scene.effect = "no_effect"
        
        changed = True
    
    return changed
```

### 3. Atomic update scene field

`core/project.py` — thêm method:

```python
def update_scene_field(self, scene_id: str, field: str, value):
    """Update single field of single scene, atomic save scenes.json."""
    target = None
    for scene in self.scenes_json.scenes:
        if scene.id == scene_id:
            target = scene
            break
    
    if target is None:
        raise ValueError(f"Scene {scene_id} not found")
    
    if not hasattr(target, field):
        raise ValueError(f"Scene has no field '{field}'")
    
    setattr(target, field, value)
    self._save_scenes_json_atomic()
    log.debug(f"Updated {scene_id}.{field} = {value}")


def update_scene(self, scene_id: str, updates: dict):
    """Update multiple fields, single atomic save."""
    target = None
    for scene in self.scenes_json.scenes:
        if scene.id == scene_id:
            target = scene
            break
    
    if target is None:
        raise ValueError(f"Scene {scene_id} not found")
    
    for key, val in updates.items():
        if hasattr(target, key):
            setattr(target, key, val)
        else:
            log.warning(f"Unknown field '{key}' for scene {scene_id}")
    
    self._save_scenes_json_atomic()


def _save_scenes_json_atomic(self):
    """Atomic write scenes.json (tmp + rename)."""
    target = self.paths.root / "scenes.json"
    tmp = target.with_suffix(".json.tmp")
    
    data = self.scenes_json.model_dump(mode="json", exclude_none=True)
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, target)
```

### 4. Thumbnail module

`core/thumbnail.py` (NEW):

```python
from pathlib import Path
import subprocess
from PIL import Image
from loguru import logger as log


THUMBNAIL_MAX_SIDE = 60
THUMBNAIL_QUALITY = 70


def generate_image_thumbnail(source_path: Path, output_path: Path) -> bool:
    """Generate 60px thumbnail from image."""
    try:
        with Image.open(source_path) as im:
            w, h = im.size
            if w > h:
                new_w = THUMBNAIL_MAX_SIDE
                new_h = int(h * THUMBNAIL_MAX_SIDE / w)
            else:
                new_h = THUMBNAIL_MAX_SIDE
                new_w = int(w * THUMBNAIL_MAX_SIDE / h)
            
            im = im.resize((new_w, new_h), Image.LANCZOS)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            im.convert("RGB").save(output_path, "JPEG", quality=THUMBNAIL_QUALITY)
        return True
    except Exception as e:
        log.warning(f"Thumbnail fail for {source_path}: {e}")
        return False


def generate_video_thumbnail(
    source_path: Path,
    output_path: Path,
    timestamp_sec: float = 1.0,
) -> bool:
    """Extract frame + thumbnail."""
    tmp_frame = output_path.with_suffix(".tmp.jpg")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp_sec),
            "-i", str(source_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(tmp_frame),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0 or not tmp_frame.exists():
            return False
        
        success = generate_image_thumbnail(tmp_frame, output_path)
        tmp_frame.unlink(missing_ok=True)
        return success
    except Exception as e:
        log.warning(f"Video thumbnail fail: {e}")
        return False


def get_thumbnail_path(project_root: Path, scene_id: str) -> Path:
    return project_root / "thumbnails" / f"{scene_id}.jpg"


def regenerate_thumbnail(
    project_root: Path,
    scene_id: str,
    visual_path: Path,
    visual_type: str,
) -> Path | None:
    """Regenerate thumbnail after gen complete."""
    thumb_path = get_thumbnail_path(project_root, scene_id)
    
    if visual_type == "image":
        ok = generate_image_thumbnail(visual_path, thumb_path)
    elif visual_type == "video":
        ok = generate_video_thumbnail(visual_path, thumb_path)
    else:
        return None
    
    return thumb_path if ok else None
```

### 5. SceneRow widget mới

`ui/scene_row.py` — refactor:

```python
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QCheckBox, QFrame, QComboBox
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

from core.thumbnail import get_thumbnail_path


VISUAL_TYPE_OPTIONS = ["image_grok", "video_grok", "slideshow_v4"]
EFFECT_OPTIONS = ["zoom_in", "zoom_out", "no_effect"]


class SceneRow(QFrame):
    edit_clicked = pyqtSignal(str)  # scene_id
    selection_changed = pyqtSignal(str, bool)
    visual_type_changed = pyqtSignal(str, str)  # scene_id, new_value
    effect_changed = pyqtSignal(str, str)  # scene_id, new_value
    
    def __init__(self, scene_id: str, project_root, parent=None):
        super().__init__(parent)
        self.scene_id = scene_id
        self.project_root = project_root
        self._suppress_signals = False
        self._build_ui()
    
    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        
        # 1. Single checkbox
        self.checkbox = QCheckBox()
        self.checkbox.stateChanged.connect(self._on_check_changed)
        layout.addWidget(self.checkbox)
        
        # 2. Thumbnail (60px)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(64, 64)
        self.thumb_label.setStyleSheet("border: 1px solid #ccc;")
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumb_label.mousePressEvent = self._on_thumb_clicked
        layout.addWidget(self.thumb_label)
        
        # 3. Scene ID
        self.label_id = QLabel(self.scene_id)
        self.label_id.setStyleSheet("font-weight: bold; min-width: 80px;")
        layout.addWidget(self.label_id)
        
        # 4. Visual type dropdown
        self.visual_type_combo = QComboBox()
        self.visual_type_combo.addItems(VISUAL_TYPE_OPTIONS)
        self.visual_type_combo.setMinimumWidth(120)
        self.visual_type_combo.currentTextChanged.connect(self._on_visual_type_changed)
        layout.addWidget(self.visual_type_combo)
        
        # 5. Effect dropdown
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(EFFECT_OPTIONS)
        self.effect_combo.setMinimumWidth(110)
        self.effect_combo.currentTextChanged.connect(self._on_effect_changed)
        layout.addWidget(self.effect_combo)
        
        # 6. Duration label (read-only)
        self.duration_label = QLabel("0s")
        self.duration_label.setStyleSheet("color: #666; min-width: 30px;")
        layout.addWidget(self.duration_label)
        
        layout.addStretch()
        
        # 7. Status icons (image/video/voice)
        self.icon_image = QLabel()
        self.icon_video = QLabel()
        self.icon_voice = QLabel()
        for w in (self.icon_image, self.icon_video, self.icon_voice):
            w.setFixedSize(24, 24)
            layout.addWidget(w)
        
        # 8. Edit button
        self.btn_edit = QPushButton("✏")
        self.btn_edit.setFixedSize(28, 28)
        self.btn_edit.setToolTip("Edit scene (full prompt + preview)")
        self.btn_edit.clicked.connect(lambda: self.edit_clicked.emit(self.scene_id))
        layout.addWidget(self.btn_edit)
    
    def update_from_scene(self, scene, scene_state: dict):
        """Update display from scene + state."""
        self._suppress_signals = True
        
        # Visual type
        self.visual_type_combo.setCurrentText(scene.visual_type)
        
        # Effect
        self.effect_combo.setCurrentText(scene.effect or "no_effect")
        
        # Duration
        self.duration_label.setText(f"{scene.duration}s")
        
        # Thumbnail
        thumb_path = get_thumbnail_path(self.project_root, self.scene_id)
        if thumb_path.exists():
            pixmap = QPixmap(str(thumb_path))
            self.thumb_label.setPixmap(pixmap.scaled(
                60, 60,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            self.thumb_label.setText("")
        else:
            self.thumb_label.setText("?")
            self.thumb_label.setStyleSheet(
                "border: 1px solid #ccc; color: #999; font-size: 24px;"
            )
        
        # Status icons (existing logic)
        # ... update icon_image, icon_video, icon_voice based on scene_state
        
        self._suppress_signals = False
    
    def _on_thumb_clicked(self, event):
        self.edit_clicked.emit(self.scene_id)
    
    def _on_check_changed(self, state):
        if self._suppress_signals: return
        selected = state == Qt.CheckState.Checked.value
        self.selection_changed.emit(self.scene_id, selected)
    
    def _on_visual_type_changed(self, value):
        if self._suppress_signals: return
        self.visual_type_changed.emit(self.scene_id, value)
    
    def _on_effect_changed(self, value):
        if self._suppress_signals: return
        self.effect_changed.emit(self.scene_id, value)
    
    def is_selected(self) -> bool:
        return self.checkbox.isChecked()
```

### 6. SceneList wire signals

`ui/scene_list.py` (or main_window.py) — connect signals:

```python
def _on_visual_type_changed(self, scene_id: str, new_value: str):
    """Save to scenes.json + refresh row display."""
    self.project.update_scene_field(scene_id, "visual_type", new_value)
    log.info(f"{scene_id} visual_type → {new_value}")


def _on_effect_changed(self, scene_id: str, new_value: str):
    """Save to scenes.json. Effect chỉ apply lúc render final, không re-render preview."""
    self.project.update_scene_field(scene_id, "effect", new_value)
    log.info(f"{scene_id} effect → {new_value}")
```

### 7. Preview Dialog mới

`ui/dialogs/preview_dialog.py` (NEW, replace cũ):

```python
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QComboBox, QSpinBox, QPushButton, QFrame, QMessageBox
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal


class PreviewDialog(QDialog):
    """Unified preview + edit dialog cho image và video."""
    
    save_requested = pyqtSignal(str, dict)  # scene_id, updates
    regen_requested = pyqtSignal(str)  # scene_id
    
    def __init__(self, scene_id, scene, scene_state, project_root, parent=None):
        super().__init__(parent)
        self.scene_id = scene_id
        self.scene = scene
        self.scene_state = scene_state
        self.project_root = project_root
        
        self.setWindowTitle(f"Preview — {scene_id}")
        self.resize(900, 750)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # 1. Visual preview
        self.visual_frame = QFrame()
        self.visual_frame.setMinimumHeight(400)
        self.visual_frame.setStyleSheet("background: #000;")
        layout.addWidget(self.visual_frame)
        self._load_visual()
        
        # 2. Editable: story
        layout.addWidget(QLabel("<b>Story (English):</b>"))
        self.story_edit = QTextEdit()
        self.story_edit.setText(self.scene.story_en or "")
        self.story_edit.setMaximumHeight(80)
        layout.addWidget(self.story_edit)
        
        # 3. Editable: imagePrompt
        layout.addWidget(QLabel("<b>Image Prompt:</b>"))
        self.image_prompt_edit = QTextEdit()
        self.image_prompt_edit.setText(self.scene.imagePrompt or "")
        self.image_prompt_edit.setMaximumHeight(120)
        layout.addWidget(self.image_prompt_edit)
        
        # 4. Editable: videoPrompt
        layout.addWidget(QLabel("<b>Video Prompt (optional):</b>"))
        self.video_prompt_edit = QTextEdit()
        self.video_prompt_edit.setText(self.scene.videoPrompt or "")
        self.video_prompt_edit.setMaximumHeight(80)
        layout.addWidget(self.video_prompt_edit)
        
        # 5. Meta row: visual_type + effect + duration
        meta_row = QHBoxLayout()
        
        meta_row.addWidget(QLabel("Visual:"))
        self.visual_combo = QComboBox()
        self.visual_combo.addItems(["image_grok", "video_grok", "slideshow_v4"])
        self.visual_combo.setCurrentText(self.scene.visual_type)
        meta_row.addWidget(self.visual_combo)
        
        meta_row.addSpacing(15)
        meta_row.addWidget(QLabel("Effect:"))
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(["zoom_in", "zoom_out", "no_effect"])
        self.effect_combo.setCurrentText(self.scene.effect or "no_effect")
        meta_row.addWidget(self.effect_combo)
        
        meta_row.addSpacing(15)
        meta_row.addWidget(QLabel("Duration:"))
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 60)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setValue(int(self.scene.duration))
        meta_row.addWidget(self.duration_spin)
        
        meta_row.addStretch()
        layout.addLayout(meta_row)
        
        # 6. Buttons
        btn_row = QHBoxLayout()
        
        btn_save = QPushButton("💾 Save")
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)
        
        btn_regen = QPushButton("🔄 Re-gen")
        btn_regen.clicked.connect(self._on_regen)
        btn_row.addWidget(btn_regen)
        
        btn_open_folder = QPushButton("📁 Folder")
        btn_open_folder.clicked.connect(self._open_folder)
        btn_row.addWidget(btn_open_folder)
        
        btn_row.addStretch()
        
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        
        layout.addLayout(btn_row)
    
    def _load_visual(self):
        visual_path = self._get_visual_path()
        layout = QVBoxLayout(self.visual_frame)
        
        if not visual_path or not visual_path.exists():
            label = QLabel("(No visual yet — click Re-gen)")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #999;")
            layout.addWidget(label)
            return
        
        if visual_path.suffix.lower() in [".jpg", ".jpeg", ".png"]:
            self._load_image(layout, visual_path)
        elif visual_path.suffix.lower() in [".mp4", ".mov"]:
            self._load_video_vlc(layout, visual_path)
    
    def _load_image(self, layout, path):
        label = QLabel()
        pixmap = QPixmap(str(path))
        label.setPixmap(pixmap.scaled(
            800, 450,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
    
    def _load_video_vlc(self, layout, path):
        try:
            import vlc
            self.vlc_instance = vlc.Instance()
            self.vlc_player = self.vlc_instance.media_player_new()
            
            media = self.vlc_instance.media_new(str(path))
            self.vlc_player.set_media(media)
            
            video_widget = QFrame()
            video_widget.setMinimumHeight(400)
            layout.addWidget(video_widget)
            
            if hasattr(video_widget, "winId"):
                self.vlc_player.set_hwnd(int(video_widget.winId()))
            
            ctrl_row = QHBoxLayout()
            btn_play = QPushButton("▶ Play")
            btn_play.clicked.connect(lambda: self.vlc_player.play())
            btn_pause = QPushButton("⏸ Pause")
            btn_pause.clicked.connect(lambda: self.vlc_player.pause())
            ctrl_row.addWidget(btn_play)
            ctrl_row.addWidget(btn_pause)
            ctrl_row.addStretch()
            layout.addLayout(ctrl_row)
        
        except ImportError:
            label = QLabel("VLC not installed — opening in system player")
            label.setStyleSheet("color: orange;")
            layout.addWidget(label)
            
            btn_open = QPushButton(f"▶ Open {path.name} externally")
            btn_open.clicked.connect(lambda: os.startfile(str(path)))
            layout.addWidget(btn_open)
    
    def _get_visual_path(self) -> Path | None:
        selected = self.scene_state.get("selected_visual", "image")
        if selected == "image":
            path_str = self.scene_state.get("image", {}).get("path")
        elif selected == "video":
            path_str = self.scene_state.get("video", {}).get("path")
        else:
            return None
        
        if not path_str:
            return None
        
        full = self.project_root / path_str
        return full if full.exists() else None
    
    def _on_save(self):
        updates = {
            "story_en": self.story_edit.toPlainText().strip(),
            "imagePrompt": self.image_prompt_edit.toPlainText().strip(),
            "videoPrompt": self.video_prompt_edit.toPlainText().strip() or None,
            "visual_type": self.visual_combo.currentText(),
            "effect": self.effect_combo.currentText(),
            "duration": self.duration_spin.value(),
        }
        self.save_requested.emit(self.scene_id, updates)
    
    def _on_regen(self):
        self._on_save()
        self.regen_requested.emit(self.scene_id)
    
    def _open_folder(self):
        path = self._get_visual_path()
        if path:
            os.startfile(str(path.parent))
```

### 8. Auto-thumbnail trong workers

`workers/batch_image.py` + `workers/single_image.py`:

```python
from core.thumbnail import regenerate_thumbnail

# Sau khi gen success:
result = await self.engine.gen_image(scene)
if result.ok:
    thumb_path = regenerate_thumbnail(
        project_root=self.project.paths.root,
        scene_id=scene.id,
        visual_path=Path(result.path),
        visual_type="image",
    )
    if thumb_path:
        log.info(f"Thumbnail: {thumb_path.name}")
    
    # Existing state update logic...
```

Tương tự cho `batch_video.py` + `single_video.py` (visual_type="video").

### 9. Effect apply trong render/composite.py

Module mới `render/zoom_effect.py`:

```python
"""
Zoom effect filter for ffmpeg zoompan.
Apply ONLY khi render final.
"""

ZOOM_RANGE = 0.2  # 1.0 → 1.2 (20%)
DEFAULT_FPS = 30
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920


def build_zoom_effect_filter(
    effect: str,
    duration_sec: float,
    fps: int = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> str:
    """
    Build zoompan filter expression.
    
    Args:
        effect: "zoom_in" | "zoom_out" | "no_effect"
        duration_sec: scene duration (sau khi adjusted bởi voice-first logic)
    
    Returns:
        ffmpeg filter string. Caller append vào filter_complex.
    """
    
    if effect == "no_effect":
        # Just scale + pad (no zoom motion)
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    
    total_frames = int(duration_sec * fps)
    zoom_target = 1.0 + ZOOM_RANGE  # 1.2
    
    if effect == "zoom_in":
        per_frame = ZOOM_RANGE / total_frames
        z_expr = f"min(zoom+{per_frame:.6f},{zoom_target})"
    elif effect == "zoom_out":
        per_frame = ZOOM_RANGE / total_frames
        z_expr = f"if(eq(on,0),{zoom_target},max(zoom-{per_frame:.6f},1.0))"
    else:
        # Fallback no_effect
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    
    # Center crop (no pan)
    return (
        f"zoompan=z='{z_expr}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s={width}x{height}:fps={fps},"
        f"setsar=1"
    )
```

`render/composite.py` — apply trong filter chain:

```python
from render.zoom_effect import build_zoom_effect_filter


def composite_scene(scene, scene_state, voice_mapping):
    visual_path = get_visual_path(scene_state)
    duration = get_adjusted_duration(scene, voice_mapping)
    effect = scene.effect or "no_effect"
    
    # Apply effect đến mọi visual_type (image/video/slideshow)
    effect_filter = build_zoom_effect_filter(effect, duration)
    
    # Build full filter chain
    filters = [effect_filter]
    
    # Add fade in/out
    if not is_first_scene:
        filters.append(f"fade=t=in:st=0:d=0.25")
    if not is_last_scene:
        filters.append(f"fade=t=out:st={duration-0.25}:d=0.25")
    
    # Subtitle drawtext
    filters.append(build_subtitle_filter(scene_state))
    
    # ... compose with voice slice + render
```

### 10. Batch video dispatch theo visual_type

`workers/batch_video.py` — refactor:

```python
async def run(self):
    for scene in selected_scenes:
        if scene.image.status != "ready":
            log.warning(f"{scene.id}: image not ready, skip")
            continue
        
        # Dispatch by visual_type
        if scene.visual_type == "image_grok":
            log.info(f"{scene.id}: image_grok, no video gen needed")
            continue  # Skip, ảnh đã đủ cho render
        
        elif scene.visual_type == "video_grok":
            log.info(f"{scene.id}: gen video_grok i2v")
            result = await self.gen_scene_with_retry(scene)
            # Generate thumbnail từ video sau gen
            if result.ok:
                regenerate_thumbnail(
                    project_root=self.project.paths.root,
                    scene_id=scene.id,
                    visual_path=Path(result.path),
                    visual_type="video",
                )
        
        elif scene.visual_type == "slideshow_v4":
            log.info(f"{scene.id}: render slideshow")
            result = await render_slideshow(scene, self.project)
            # Generate thumbnail từ video output
            if result.ok:
                regenerate_thumbnail(...)
```

→ KHÔNG cần dropdown ở button. Logic dispatch theo visual_type của từng scene.

### 11. Install python-vlc

`requirements.txt`:
```
python-vlc>=3.0.0
Pillow>=10.0.0
```

User cần install VLC: https://www.videolan.org/vlc/

Document trong README.

---

## Test Plan

### Test 1: Schema migration
- Load scenes.json cũ không có field `effect`
- Verify auto-fill: image_grok và slideshow_v4 alternate zoom_in/zoom_out, video_grok = no_effect
- Verify scenes.json saved với field mới

### Test 2: Thumbnails load
- Load project có 6 ảnh
- Verify 6 thumbnails tạo trong test_run/thumbnails/
- Verify rows hiển thị thumbnails đúng

### Test 3: Dropdown đổi visual_type
- Click dropdown SCENE-01 → đổi từ image_grok → video_grok
- Verify scenes.json updated
- Verify status icons update (video=pending)

### Test 4: Dropdown đổi effect
- Click dropdown SCENE-01 → đổi từ zoom_in → zoom_out
- Verify scenes.json updated
- Re-render preview → KHÔNG có effect apply (chỉ render final mới apply)

### Test 5: Click thumbnail → Preview Dialog
- Click thumbnail SCENE-01
- Verify dialog mở với:
  - Ảnh hiển thị
  - Story, prompts editable
  - Visual + Effect + Duration sync với row
- Edit imagePrompt → Save
- Verify scenes.json updated, dialog đóng (hoặc giữ)

### Test 6: Re-gen từ dialog
- Edit prompt
- Click Re-gen
- Verify save trước rồi mới gen
- Verify thumbnail update sau gen

### Test 7: Video preview VLC
- Click thumbnail của scene có video_grok
- Verify VLC player embed, có nút Play/Pause
- Test fallback nếu không có VLC

### Test 8: Render final với effect
- 1 scene image_grok + zoom_in
- 1 scene image_grok + zoom_out
- 1 scene video_grok + no_effect
- 1 scene slideshow_v4 + zoom_in
- Click Render final
- Verify final.mp4:
  - Scene 1: ảnh zoom in slow
  - Scene 2: ảnh zoom out slow
  - Scene 3: video không có thêm zoom
  - Scene 4: slideshow + zoom in

### Test 9: Batch video dispatch
- 2 scenes: 1 image_grok, 1 video_grok
- Click Batch video
- Verify: scene image_grok skip, scene video_grok gen i2v

---

## Build Order

1. **Schema update + auto-fill effects** (1h)
2. **Project.update_scene_field + atomic save** (30 phút)
3. **core/thumbnail.py** (1h)
4. **render/zoom_effect.py** (1h)
5. **Refactor SceneRow widget** (2-3h) — bỏ tick 2, add dropdowns + thumbnail
6. **Wire signals scenes.json save** (30 phút)
7. **PreviewDialog mới** (2h) — unified image+video, edit fields
8. **VLC integration** (1h)
9. **Auto-thumbnail trong workers** (30 phút)
10. **render/composite.py update** (1h) — apply zoom effect
11. **Batch video dispatch** (1h) — theo visual_type

**Total: ~7-9h**

---

## Confirm trước khi code

- [ ] Schema thêm field `effect`, bỏ `ken_burns_self` khỏi visual_type enum
- [ ] Auto-fill alternate khi load scenes.json (only nếu missing)
- [ ] Thumbnail max-side 60px, cache trong `test_run/thumbnails/`
- [ ] Bỏ checkbox 2, bỏ ⚠ + 🔄 ở cuối row
- [ ] Visual type + Effect dropdowns trong row, save ngay khi đổi
- [ ] Effect apply CHỈ lúc render final (KHÔNG preview/regen)
- [ ] Batch video dispatch theo visual_type, không dropdown ở button
- [ ] python-vlc cho video preview, fallback os.startfile

Build từng phần, test sau mỗi phần.
