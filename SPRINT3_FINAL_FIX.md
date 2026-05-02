# Sprint 3 Final — Render Fix + Voice-Led Timeline + Cleanup

> **Goal**: Fix zoom jitter + slideshow trắng + voice-led timeline + cleanup V1/V2.
> **Effort**: 5-6h
> **Mode**: Build sequential, test sau mỗi step.

---

## Tổng quan

8 changes trong MD này:

| # | Change | File | Severity | Effort |
|---|---|---|---|---|
| 1 | Auto-clone `scenes_edited.json` | `core/project.py` | HIGH | 1h |
| 2 | Bỏ wizard "Import Voice Files" | `ui/dialogs/voice_import.py` (xóa) + `main_window.py` | MEDIUM | 30 phút |
| 3 | UI redesign Review dialog 2-column | `ui/dialogs/voice_align_review.py` | MEDIUM | 1.5h |
| 4 | Fix zoom jitter image_grok | `render/visual_fit.py` `build_zoom_filter` | HIGH | 30 phút |
| 5 | Fix slideshow trắng + zoom video jitter | `render/visual_fit.py` `_zoom_tail` + `build_video_filter` | HIGH | 30 phút |
| 6 | Voice-led timeline với freeze frame pause | `render/composite.py` (sau rename) + `workers/render_worker.py` | HIGH | 1.5h |
| 7 | Cleanup V1 redundancy | Xóa 4 files legacy | LOW | 30 phút |
| 8 | Rename v2 → main | Đổi tên `composite_v2` → `composite`, `assemble_v2` → `assemble` | LOW | 15 phút |

---

## CHANGE 1: Auto-clone `scenes_edited.json`

### Logic

```
test_live/
├── scenes.json              ← ORIGINAL, read-only sau load đầu tiên
├── scenes_edited.json       ← AUTO-CLONE on load, app modify
└── ...
```

- Khi `Project.load(path)` chạy lần đầu:
  - Đọc `scenes.json`
  - Nếu **không có** `scenes_edited.json` → clone từ `scenes.json`
  - Nếu **đã có** `scenes_edited.json` → load file đó (giữ user edits)
- App đọc/ghi `scenes_edited.json` cho mọi operation
- Button "🔄 Reset to design" → overwrite `scenes_edited.json` từ `scenes.json`

### File: `core/project.py`

Tìm function `Project.load()` hoặc `__init__()` — nơi load scenes.json.

Thêm logic:

```python
import shutil

def _load_scenes(self) -> dict:
    """
    Load scenes_edited.json if exists, else clone from scenes.json.
    """
    scenes_path = self.paths.root / "scenes.json"
    edited_path = self.paths.root / "scenes_edited.json"
    
    if not scenes_path.exists():
        raise FileNotFoundError(f"scenes.json not found: {scenes_path}")
    
    if not edited_path.exists():
        log.info(f"First load: cloning scenes.json → scenes_edited.json")
        shutil.copy(scenes_path, edited_path)
    
    # Load from edited file
    with edited_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    log.info(f"Loaded scenes_edited.json: {len(data.get('scenes', []))} scenes")
    return data


def reset_to_design(self):
    """Restore scenes_edited.json from scenes.json (lose all edits)."""
    scenes_path = self.paths.root / "scenes.json"
    edited_path = self.paths.root / "scenes_edited.json"
    
    if not scenes_path.exists():
        raise FileNotFoundError(f"scenes.json not found")
    
    shutil.copy(scenes_path, edited_path)
    log.info("Reset: scenes_edited.json restored from scenes.json")
    
    # Reload
    self.scenes_json = self._load_scenes()


def save_scenes_edited(self, data: dict):
    """Save modified scenes data to scenes_edited.json."""
    edited_path = self.paths.root / "scenes_edited.json"
    with edited_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"Saved scenes_edited.json")
```

### File: `core/paths.py`

Thêm property:

```python
@property
def scenes_edited(self) -> Path:
    return self.root / "scenes_edited.json"

@property
def scenes_original(self) -> Path:
    return self.root / "scenes.json"
```

### File: `ui/main_window.py`

Replace mọi reference `scenes.json` save → dùng `save_scenes_edited()`:

```python
# CŨ:
# self._save_scenes_to_file()  # ghi scenes.json
# 
# MỚI:
def _save_scenes(self):
    self.project.save_scenes_edited(
        self.project.scenes_json.model_dump(mode="json")
    )
```

Add button "🔄 Reset to design" trong toolbar:

```python
btn_reset = QPushButton("🔄 Reset to design")
btn_reset.setToolTip("Restore scenes from scenes.json (lose edits)")
btn_reset.clicked.connect(self._on_reset_to_design)


def _on_reset_to_design(self):
    reply = QMessageBox.question(
        self,
        "Reset to design?",
        "Tất cả edits sẽ mất. Restore scenes_edited.json từ scenes.json?",
    )
    if reply == QMessageBox.StandardButton.Yes:
        self.project.reset_to_design()
        self._reload_project_ui()
```

### Test

```
1. Load project test_live lần đầu
   → Verify scenes_edited.json được tạo
2. Edit effect 1 scene (vd zoom_in → zoom_out)
   → Verify scenes_edited.json thay đổi
   → scenes.json KHÔNG đổi
3. Reload project
   → Verify edit vẫn còn (load từ scenes_edited)
4. Click "Reset to design"
   → Verify scenes_edited.json = scenes.json
   → Edit cũ mất
```

---

## CHANGE 2: Bỏ wizard "Import Voice Files"

### Lý do

Plan D auto-match voice → scenes bằng fuzzy match. Wizard checkbox manual không còn cần thiết.

### File cần XÓA

```
ui/dialogs/voice_import.py
```

### File cần UPDATE: `ui/main_window.py`

Tìm phần:

```python
# CŨ:
self.btn_import_voice = QPushButton("🎤 Import voice")
self.btn_import_voice.clicked.connect(self._open_voice_import_wizard)
```

Thay bằng:

```python
self.btn_process_voice = QPushButton("🎤 Process voice")
self.btn_process_voice.setToolTip("Auto-align voice to scenes (Plan D)")
self.btn_process_voice.clicked.connect(self._on_process_voice)


def _on_process_voice(self):
    """Auto-trigger Plan D alignment, no wizard."""
    if not self.project:
        return
    
    voice_dir = self.project.paths.root / "voice"
    
    # Check folder has audio files
    has_audio = any(voice_dir.glob("*.mp3")) or any(voice_dir.glob("*.wav"))
    if not has_audio:
        QMessageBox.warning(
            self,
            "No voice",
            f"Folder voice/ trống. Bỏ file mp3/wav vào: {voice_dir}"
        )
        return
    
    # Disable button during run
    self.btn_process_voice.setEnabled(False)
    self.btn_process_voice.setText("🎤 Processing...")
    
    # Get scenes from scenes_edited.json
    scenes_data = [
        s.model_dump(mode="json")
        for s in self.project.scenes_json.scenes
    ]
    
    self._voice_worker = VoiceAlignWorker(
        scenes=scenes_data,
        voice_dir=voice_dir,
        output_dir=self.project.paths.root,
        whisper_model="base",
        language="en",
    )
    self._voice_worker.align_done.connect(self._on_voice_align_done)
    self._voice_worker.align_failed.connect(self._on_voice_align_failed)
    self._voice_worker.start()


def _on_voice_align_done(self, voice_mapping: dict):
    self.btn_process_voice.setEnabled(True)
    self.btn_process_voice.setText("🎤 Process voice")
    
    # Open Review dialog (Change 3)
    from ui.dialogs.voice_align_review import VoiceAlignReviewDialog
    
    # Get whisper words from worker (cần expose)
    whisper_words = self._voice_worker.whisper_words  # add property
    
    scenes_data = [
        s.model_dump(mode="json")
        for s in self.project.scenes_json.scenes
    ]
    
    dialog = VoiceAlignReviewDialog(
        voice_mapping=voice_mapping,
        scenes_data=scenes_data,
        whisper_words=whisper_words,
        parent=self,
    )
    dialog.save_requested.connect(self._on_voice_mapping_saved)
    result = dialog.exec()
    
    if result == 2:
        # Re-align all clicked
        self._on_process_voice()


def _on_voice_align_failed(self, reason: str):
    self.btn_process_voice.setEnabled(True)
    self.btn_process_voice.setText("🎤 Process voice")
    QMessageBox.critical(self, "Voice align failed", reason)


def _on_voice_mapping_saved(self, voice_mapping: dict):
    """Save voice_mapping.json after user reviews."""
    import json
    output_path = self.project.paths.root / "voice_mapping.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(voice_mapping, f, ensure_ascii=False, indent=2)
    log.info(f"Saved voice_mapping.json")
```

### File: `workers/voice_align_worker.py`

Expose `whisper_words` để dialog dùng cho Move buttons:

```python
class VoiceAlignWorker(AsyncTaskWorker):
    # ...
    
    def __init__(self, ...):
        super().__init__()
        # ...
        self.whisper_words = []  # Expose for dialog
    
    async def run(self):
        # ... existing code ...
        # Sau Whisper transcribe, save:
        self.whisper_words = whisper_words
        # ...
```

### Test

```
1. Click "Process voice" (KHÔNG còn wizard)
2. Verify alignment chạy ngay không hỏi
3. Verify Review dialog mở sau khi xong
4. Click "Re-align all" → verify chạy lại
```

---

## CHANGE 3: UI Review dialog 2-column

### File: `ui/dialogs/voice_align_review.py` — REWRITE

```python
"""Voice align review dialog — compact 2-column layout with realign features."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QFrame, QScrollArea, QWidget, QTextEdit,
    QSizePolicy, QMessageBox,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt, pyqtSignal


SCORE_COLORS = {
    "high": "#2e7d32",      # green ≥ 90
    "medium": "#f57c00",    # orange 70-89
    "low": "#c62828",       # red < 70
}


class VoiceAlignReviewDialog(QDialog):
    save_requested = pyqtSignal(dict)
    
    def __init__(self, voice_mapping: dict, scenes_data: list, whisper_words: list, parent=None):
        super().__init__(parent)
        self.voice_mapping = voice_mapping
        self.scenes_data = scenes_data
        self.whisper_words = whisper_words
        
        self.setWindowTitle("Voice Alignment Review")
        self.resize(1100, 750)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        stats = self.voice_mapping.get("stats", {})
        header = QLabel(
            f"<b>Plan D alignment</b> — "
            f"scenes: {len(self.voice_mapping.get('scenes', []))} | "
            f"deterministic: {stats.get('deterministic_pass', 0)} | "
            f"LLM fallback: {stats.get('llm_fallback_count', 0)} | "
            f"silent: {stats.get('silent', 0)} | "
            f"voice files: {len(self.voice_mapping.get('voice_files', []))}"
        )
        layout.addWidget(header)
        
        # Scrollable scene list
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        
        self.scenes_container = QWidget()
        scenes_layout = QVBoxLayout(self.scenes_container)
        scenes_layout.setSpacing(6)
        
        for vs in self.voice_mapping.get("scenes", []):
            row = self._build_scene_row(vs)
            scenes_layout.addWidget(row)
        scenes_layout.addStretch()
        
        self.scroll.setWidget(self.scenes_container)
        layout.addWidget(self.scroll)
        
        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_realign = QPushButton("Re-align all (rerun Plan D)")
        btn_realign.clicked.connect(lambda: self.done(2))
        btn_row.addWidget(btn_realign)
        btn_row.addStretch()
        
        btn_save = QPushButton("Save")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        
        layout.addLayout(btn_row)
    
    def _build_scene_row(self, vs: dict) -> QFrame:
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("""
            QFrame { border: 1px solid #ccc; border-radius: 4px; padding: 8px; }
            QTextEdit { background: #fafafa; border: 1px solid #ddd; }
        """)
        outer = QVBoxLayout(frame)
        outer.setSpacing(8)
        
        # Header: ID + Match score
        top = QHBoxLayout()
        top.addWidget(QLabel(f"<b style='font-size:11pt'>{vs['id']}</b>"))
        top.addStretch()
        
        score = vs.get("score") or 0
        method = vs.get("method", "—")
        if vs.get("is_silent"):
            color = "#888"
            score_text = f"SILENT ({method})"
        else:
            key = "high" if score >= 90 else "medium" if score >= 70 else "low"
            color = SCORE_COLORS[key]
            score_text = f"Match: {score:.1f}% ({method})"
        
        score_label = QLabel(score_text)
        score_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        top.addWidget(score_label)
        outer.addLayout(top)
        
        if vs.get("is_silent"):
            outer.addWidget(QLabel("<i>Silent scene — keeps design duration</i>"))
            return frame
        
        # 2-column grid
        grid = QGridLayout()
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setSpacing(8)
        
        # Row 1: 📜 Script (left) + Render duration (right)
        grid.addWidget(QLabel("📜 <b>Script</b>"), 0, 0)
        right_label = QLabel("Render duration")
        right_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        grid.addWidget(right_label, 0, 1)
        
        # Row 2: Script text + Render mode
        scene_id = vs["id"]
        script_text = next(
            (s.get("story_en", "") for s in self.scenes_data if s["id"] == scene_id),
            "",
        )
        script_edit = QTextEdit()
        script_edit.setPlainText(script_text)
        script_edit.setReadOnly(True)
        script_edit.setMaximumHeight(70)
        script_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid.addWidget(script_edit, 1, 0)
        
        grid.addWidget(self._build_render_panel(vs), 1, 1)
        
        # Row 3: 🎤 Voice (left) + Voice timing (right)
        grid.addWidget(QLabel("🎤 <b>Voice</b>"), 2, 0)
        timing_header = QLabel("Voice timing")
        timing_header.setAlignment(Qt.AlignmentFlag.AlignRight)
        grid.addWidget(timing_header, 2, 1)
        
        # Row 4: Voice text + Timing info
        voice_edit = QTextEdit()
        voice_edit.setPlainText(vs.get("matched_text", ""))
        voice_edit.setReadOnly(True)
        voice_edit.setMaximumHeight(70)
        voice_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid.addWidget(voice_edit, 3, 0)
        
        grid.addWidget(self._build_timing_panel(vs), 3, 1)
        
        outer.addLayout(grid)
        
        # Move buttons
        idx = self._get_scene_index(scene_id)
        total = len(self.voice_mapping["scenes"])
        
        btn_row = QHBoxLayout()
        btn_head = QPushButton("◀ Move HEAD up to previous")
        btn_head.setEnabled(idx > 0)
        btn_head.clicked.connect(lambda c=False, sid=scene_id: self._on_move_head(sid))
        btn_row.addWidget(btn_head)
        btn_row.addStretch()
        
        btn_tail = QPushButton("Move TAIL down to next ▶")
        btn_tail.setEnabled(idx < total - 1)
        btn_tail.clicked.connect(lambda c=False, sid=scene_id: self._on_move_tail(sid))
        btn_row.addWidget(btn_tail)
        outer.addLayout(btn_row)
        
        return frame
    
    def _build_render_panel(self, vs: dict) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        row = QHBoxLayout()
        mode_combo = QComboBox()
        mode_combo.addItems(["voice", "design", "custom"])
        current_mode = vs.get("render_mode", "voice")
        mode_combo.setCurrentText(current_mode)
        mode_combo.setObjectName(f"mode_{vs['id']}")
        row.addWidget(mode_combo)
        
        custom_spin = QDoubleSpinBox()
        custom_spin.setRange(0.5, 60.0)
        custom_spin.setSuffix(" s")
        custom_spin.setSingleStep(0.5)
        custom_spin.setValue(vs.get("custom_duration") or vs.get("duration_original", 5))
        custom_spin.setObjectName(f"custom_{vs['id']}")
        custom_spin.setEnabled(current_mode == "custom")
        row.addWidget(custom_spin)
        
        mode_combo.currentTextChanged.connect(
            lambda mode, spin=custom_spin: spin.setEnabled(mode == "custom")
        )
        layout.addLayout(row)
        
        design = vs.get("duration_original", 0)
        info = QLabel(f"Design: {design}s")
        info.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(info)
        layout.addStretch()
        return panel
    
    def _build_timing_panel(self, vs: dict) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        vi = vs.get("voice_in") or 0
        vo = vs.get("voice_out") or 0
        dur = vo - vi
        
        timing = QLabel(f"⏱ {vi:.2f} → {vo:.2f}s")
        timing.setStyleSheet("font-family: monospace; font-size: 9pt;")
        layout.addWidget(timing)
        
        dur_label = QLabel(f"Duration: <b>{dur:.2f}s</b>")
        dur_label.setStyleSheet("font-size: 9pt;")
        layout.addWidget(dur_label)
        layout.addStretch()
        return panel
    
    def _get_scene_index(self, scene_id: str) -> int:
        for i, vs in enumerate(self.voice_mapping["scenes"]):
            if vs["id"] == scene_id:
                return i
        return -1
    
    def _on_move_head(self, scene_id: str):
        from voice.realign_helper import move_head_to_previous
        try:
            self.voice_mapping = move_head_to_previous(
                voice_mapping=self.voice_mapping,
                scene_id=scene_id,
                whisper_words=self.whisper_words,
                scenes_data=self.scenes_data,
            )
            self._refresh_ui()
        except Exception as e:
            QMessageBox.warning(self, "Move HEAD failed", str(e))
    
    def _on_move_tail(self, scene_id: str):
        from voice.realign_helper import move_tail_to_next
        try:
            self.voice_mapping = move_tail_to_next(
                voice_mapping=self.voice_mapping,
                scene_id=scene_id,
                whisper_words=self.whisper_words,
                scenes_data=self.scenes_data,
            )
            self._refresh_ui()
        except Exception as e:
            QMessageBox.warning(self, "Move TAIL failed", str(e))
    
    def _refresh_ui(self):
        layout = self.scenes_container.layout()
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for vs in self.voice_mapping.get("scenes", []):
            layout.addWidget(self._build_scene_row(vs))
        layout.addStretch()
    
    def _on_save(self):
        for vs in self.voice_mapping["scenes"]:
            scene_id = vs["id"]
            mode_combo = self.findChild(QComboBox, f"mode_{scene_id}")
            custom_spin = self.findChild(QDoubleSpinBox, f"custom_{scene_id}")
            
            if mode_combo:
                vs["render_mode"] = mode_combo.currentText()
            if custom_spin and vs.get("render_mode") == "custom":
                vs["custom_duration"] = custom_spin.value()
            
            # Calculate render_duration
            if vs.get("is_silent"):
                vs["render_duration"] = vs.get("duration_original", 5)
            elif vs.get("render_mode") == "voice":
                vs["render_duration"] = (vs.get("voice_out") or 0) - (vs.get("voice_in") or 0)
            elif vs.get("render_mode") == "design":
                vs["render_duration"] = vs.get("duration_original", 5)
            else:
                vs["render_duration"] = vs.get("custom_duration", vs.get("duration_original", 5))
        
        self.save_requested.emit(self.voice_mapping)
        self.accept()
```

### Test

- Layout 2-column: 📜 trái, Render right; 🎤 trái, Timing right
- Match score color OK
- Move HEAD/TAIL buttons enable/disable đúng
- Save export render_mode + custom_duration

---

## CHANGE 4: Fix zoom jitter — `build_zoom_filter` (image_grok)

### Bugs detected (đã verify từ stack search)

1. **Thiếu pre-scale upscale** trước zoompan → ffmpeg interpolate pixel → jitter
2. **Thiếu trunc()** trên x/y → rounding random ±1px → shake
3. **`d=1` SAI cho image với `-loop 1`** → zoompan reset mỗi frame, broken motion

### File: `render/visual_fit.py`

Replace `build_zoom_filter`:

```python
def build_zoom_filter(
    effect: str,
    duration_sec: float,
    width: int,
    height: int,
    fps: int = FPS,
) -> str:
    """Build smooth zoompan filter for a still image (image_grok with -loop 1).
    
    Smooth zoom strategy (verified from stack search):
    1. Pre-scale image 4x BEFORE zoompan → more pixels available, less rounding
    2. trunc() on x/y → eliminate sub-pixel shake
    3. d=total_frames for image (loop=1 emits 1 input frame, zoompan extends to N output)
    """
    if effect == "no_effect":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
    
    total_frames = max(1, int(round(duration_sec * fps)))
    upscale_w = width * 4   # 7680 for 1920
    upscale_h = height * 4  # 4320 for 1080
    zoom_target = 1.0 + ZOOM_RANGE  # 1.2
    span = float(ZOOM_RANGE)
    
    if effect == "zoom_in":
        z_expr = f"min(1.0+{span:.4f}*on/{total_frames},{zoom_target:.4f})"
    elif effect == "zoom_out":
        z_expr = f"max({zoom_target:.4f}-{span:.4f}*on/{total_frames},1.0)"
    else:
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
    
    return (
        f"scale={upscale_w}:{upscale_h}:flags=lanczos,"            # ⭐ Pre-scale 4x
        f"zoompan=z='{z_expr}':"
        f"x='trunc(iw/2-(iw/zoom/2))':"                              # ⭐ trunc x
        f"y='trunc(ih/2-(ih/zoom/2))':"                              # ⭐ trunc y
        f"d={total_frames}:"                                         # ⭐ d=total_frames cho image
        f"s={width}x{height}:fps={fps},"
        f"setsar=1"
    )
```

### Test

```bash
# Render SCENE-05 (image_grok, zoom_out)
# Play scene_renders/SCENE-05.mp4 ở slow speed (0.5x)
# Verify:
# - Zoom mượt, không giật cục
# - Camera mở rộng từ từ (zoom_out)
# - Frame quality không bị mờ (upscale 4x giúp giữ detail)
```

---

## CHANGE 5: Fix slideshow trắng + zoom video jitter

### File: `render/visual_fit.py`

Replace `_zoom_tail` và `build_video_filter`:

```python
def _zoom_tail(
    effect: str,
    duration_sec: float,
    width: int,
    height: int,
    fps: int,
) -> str | None:
    """Smooth zoompan tail for video stream (video_grok / slideshow).
    
    For video input: d=1 (one input frame → one output frame).
    Pre-scale + trunc() applied here too.
    """
    if effect == "no_effect":
        return None
    
    total_frames = max(1, int(round(duration_sec * fps)))
    upscale_w = width * 4
    upscale_h = height * 4
    zoom_target = 1.0 + ZOOM_RANGE
    span = float(ZOOM_RANGE)
    
    if effect == "zoom_in":
        z_expr = f"min(1.0+{span:.4f}*on/{total_frames},{zoom_target:.4f})"
    elif effect == "zoom_out":
        z_expr = f"max({zoom_target:.4f}-{span:.4f}*on/{total_frames},1.0)"
    else:
        return None
    
    # IMPORTANT: scale up BEFORE zoompan, then back to canvas size
    return (
        f"scale={upscale_w}:{upscale_h}:flags=lanczos,"            # ⭐ Pre-scale 4x
        f"zoompan=z='{z_expr}':"
        f"x='trunc(iw/2-(iw/zoom/2))':"                              # ⭐ trunc
        f"y='trunc(ih/2-(ih/zoom/2))':"                              # ⭐ trunc
        f"d=1:"                                                       # ⭐ d=1 cho video
        f"s={width}x{height}:fps={fps}"
    )


def build_video_filter(
    duration_design: float,
    duration_adjusted: float,
    effect: str,
    width: int,
    height: int,
    fps: int = FPS,
) -> str:
    """Filter chain for a video-source visual (video_grok / slideshow .mp4).
    
    Pipeline:
      1. setpts (speedup) OR tpad (extend) to fit duration
      2. scale + pad to canvas size
      3. fps normalize
      4. Optional zoom tail (with pre-scale built in)
      5. setsar
    
    Speedup capped at 1.2x (per spec). If duration ratio > 1.2x, speedup
    1.2x then trim to target duration.
    """
    parts: list[str] = []
    
    if abs(duration_adjusted - duration_design) >= TOLERANCE:
        if duration_adjusted < duration_design:
            ratio = duration_design / duration_adjusted
            
            if ratio <= 1.2:
                # Speedup is enough
                pts_factor = duration_adjusted / duration_design
                log.info(
                    f"video speedup: design={duration_design}s adjusted={duration_adjusted}s "
                    f"setpts={pts_factor:.4f}*PTS (ratio {ratio:.2f}x)"
                )
                parts.append(f"setpts={pts_factor:.4f}*PTS")
            else:
                # Speedup max 1.2x then trim
                pts_factor_capped = 1.0 / 1.2  # ≈ 0.8333
                log.info(
                    f"video speedup capped 1.2x + trim: design={duration_design}s "
                    f"adjusted={duration_adjusted}s (raw ratio {ratio:.2f}x)"
                )
                parts.append(f"setpts={pts_factor_capped:.4f}*PTS")
                # After 1.2x speed, length = duration_design / 1.2
                # Need to trim to duration_adjusted
                parts.append(f"trim=duration={duration_adjusted:.3f}")
                parts.append("setpts=PTS-STARTPTS")
        else:
            # Visual shorter than render → freeze last frame
            extra = duration_adjusted - duration_design
            log.info(
                f"video extend: design={duration_design}s adjusted={duration_adjusted}s "
                f"freeze tail +{extra:.2f}s"
            )
            parts.append(f"tpad=stop_mode=clone:stop_duration={extra:.3f}")
    
    parts.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
    parts.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    parts.append(f"fps={fps}")
    
    zoom = _zoom_tail(effect, duration_adjusted, width, height, fps)
    if zoom is not None:
        parts.append(zoom)
    
    parts.append("setsar=1")
    return ",".join(parts)
```

### Test

```bash
# 1. Test slideshow (SCENE-03)
# Render → check renders/SCENE-03.mp4
# Verify bitrate > 1 Mbps (KHÔNG còn 18 Kbps trắng)
# Play → verify cup, notebook, pen hiện đúng

# 2. Test video_grok với zoom_out (SCENE-02)
# Render → play renders/SCENE-02.mp4
# Verify zoom mượt, no jitter
```

---

## CHANGE 6: Voice-led timeline với freeze frame pause

### Logic mới

**Trusted source = VOICE timestamps.**

```
Voice mp3 timeline:
0.00 ──── 6.42      SCENE-01 voice
6.42 ──── 7.38      [pause natural 0.96s]
7.38 ──── 13.22     SCENE-02 voice
13.22 ─── 13.76     [pause 0.54s]
13.76 ─── 19.74     SCENE-03 voice
...

Render output (per scene = voice + freeze frame for next pause):
SCENE-01 render = 0 → 6.42 + freeze 0.96s = 7.38s total
  - Visual fit to 6.42s (speedup max 1.2x or extend)
  - Freeze last frame for 0.96s
  - Audio: voice + silence 0.96s

SCENE-02 render = 7.38 → 13.22 + freeze 0.54s = 6.38s total
...
```

→ Visual KHÔNG bị cắt thái quá. Pause natural giữ nguyên.

### Schema voice_mapping update

Add field per scene:

```json
{
  "id": "SCENE-01",
  "voice_in": 0.0,
  "voice_out": 6.42,
  "duration_original": 8.0,
  "duration_adjusted": 6.42,
  "render_duration": 7.38,         // ⭐ NEW: voice + freeze pause
  "render_mode": "voice",
  "freeze_pause_after": 0.96,      // ⭐ NEW: pause to next scene
  ...
}
```

### File: `voice/voice_aligner.py`

Thêm logic build pause khi build voice_mapping:

```python
def add_freeze_pauses(scenes_voice_mapping: list[dict]) -> list[dict]:
    """Add freeze_pause_after to each scene based on next scene's voice_in."""
    for i, vs in enumerate(scenes_voice_mapping):
        if vs.get("is_silent"):
            vs["freeze_pause_after"] = 0.0
            continue
        
        # Find next non-silent scene
        next_voice_in = None
        for j in range(i + 1, len(scenes_voice_mapping)):
            nxt = scenes_voice_mapping[j]
            if not nxt.get("is_silent") and nxt.get("voice_in") is not None:
                next_voice_in = nxt["voice_in"]
                break
        
        if next_voice_in is None:
            # Last non-silent scene, no pause after
            vs["freeze_pause_after"] = 0.0
        else:
            pause = next_voice_in - vs["voice_out"]
            vs["freeze_pause_after"] = max(0.0, pause)
    
    return scenes_voice_mapping
```

Call this after building voice_mapping before save.

### File: `render/composite.py` (sau rename từ composite_v2)

Update logic build filter chain để include freeze pause:

```python
def composite_scene(
    scene: dict,
    voice_scene: dict,
    visual_path: Path,
    voice_files: list[dict],
    project_root: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int = FPS,
) -> Path:
    visual_path = Path(visual_path)
    output_path = Path(output_path)
    project_root = Path(project_root)
    
    duration_design = float(voice_scene["duration_original"])
    voice_in = float(voice_scene.get("voice_in") or 0)
    voice_out = float(voice_scene.get("voice_out") or 0)
    voice_dur = max(0.0, voice_out - voice_in) if not voice_scene.get("is_silent") else 0
    
    freeze_pause = float(voice_scene.get("freeze_pause_after") or 0)
    
    # Determine render_duration based on render_mode
    render_mode = voice_scene.get("render_mode", "voice")
    if voice_scene.get("is_silent"):
        voice_part_dur = duration_design
    elif render_mode == "voice":
        voice_part_dur = voice_dur
    elif render_mode == "design":
        voice_part_dur = duration_design
    else:  # custom
        voice_part_dur = float(voice_scene.get("custom_duration") or duration_design)
    
    total_render_dur = voice_part_dur + freeze_pause
    
    visual_type = scene["visual_type"]
    effect = scene.get("effect", "no_effect") or "no_effect"
    
    log.info(
        f"composite {scene['id']}: visual={visual_type} effect={effect} "
        f"design={duration_design}s voice_part={voice_part_dur}s "
        f"freeze_pause={freeze_pause}s total={total_render_dur}s"
    )
    
    # === Build visual filter ===
    is_static = visual_type == "image_grok" or visual_path.suffix.lower() in _STATIC_IMAGE_EXTS
    
    visual_filter = build_visual_filter_with_fit(
        visual_type=visual_type,
        duration_design=duration_design,
        duration_adjusted=voice_part_dur,  # Visual fit to voice part only
        effect=effect,
        width=width,
        height=height,
        fps=fps,
        source_is_video=not is_static,
    )
    
    # Append freeze pause (clone last frame)
    if freeze_pause > 0:
        visual_filter += f",tpad=stop_mode=clone:stop_duration={freeze_pause:.3f}"
    
    visual_filter += ",setsar=1"
    
    if is_static:
        visual_input = ["-loop", "1", "-i", str(visual_path)]
    else:
        visual_input = ["-i", str(visual_path)]
    
    # === Build audio filter ===
    cleanup_files = []
    if voice_scene.get("is_silent"):
        audio_input, audio_filter = get_silent_audio_args(total_render_dur)
    else:
        audio_input, audio_filter, concat_list = get_voice_slice_args(
            voice_files=voice_files,
            voice_in=voice_in,
            voice_out=voice_out,
            project_root=project_root,
        )
        cleanup_files.append(concat_list)
        
        # Pad silence for freeze_pause + render_mode tail extend (if any)
        total_silence = freeze_pause
        if voice_part_dur > voice_dur + 0.01:
            # Render mode design/custom extends voice_part beyond voice
            total_silence += voice_part_dur - voice_dur
        
        if total_silence > 0:
            audio_filter += f",apad=pad_dur={total_silence:.3f}"
            log.info(f"  audio pad: voice={voice_dur:.2f}s pad +{total_silence:.2f}s")
    
    filter_complex = (
        f"[0:v]{visual_filter}[v];"
        f"[1:a]{audio_filter}[a]"
    )
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *visual_input,
        *audio_input,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-t", f"{total_render_dur:.3f}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-r", str(fps),
        str(output_path),
    ]
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600,
        )
    finally:
        for f in cleanup_files:
            try:
                f.unlink()
                f.parent.rmdir()
            except OSError:
                pass
    
    if result.returncode != 0:
        log.error(f"composite {scene['id']} failed: {(result.stderr or '')[-1500:]}")
        raise RuntimeError(f"FFmpeg composite failed for {scene['id']}")
    
    log.info(f"  -> {output_path.name}")
    return output_path
```

### File: `voice/ass_generator.py`

Update timing để include freeze pause:

```python
# Trong loop scenes:
for vs in voice_mapping.get("scenes", []):
    # Use freeze_pause + voice_part for total scene duration
    voice_part = vs.get("render_duration") or vs.get("duration_adjusted", 0)
    freeze_pause = vs.get("freeze_pause_after", 0)
    scene_dur_ms = int(round((voice_part + freeze_pause) * 1000))
    
    # Subtitle phrases timing — relative to voice_in, NOT including freeze pause
    # (subtitle ends when voice ends, freeze pause has no subtitle)
    # ... existing logic ...
    
    cursor_ms += scene_dur_ms
```

### Test

```
1. Re-align voice (Plan D adds freeze_pause_after)
2. Verify voice_mapping.json has freeze_pause_after per scene
3. Render
4. Play final.mp4:
   ✓ Each scene's visual ends with frozen frame for ~0.5-1s pause
   ✓ Audio has natural pause between scenes (silent)
   ✓ Subtitle disappears at voice end (not during freeze pause)
   ✓ Total duration = sum of (voice + freeze_pause) per scene
   ✓ Visual KHÔNG bị cắt thái quá nữa
```

---

## CHANGE 7: Cleanup V1 redundancy

### Verify trước khi xóa

Claude Code làm:

```powershell
# Check render_worker đang import gì
Select-String -Path workers\render_worker.py -Pattern "from render"

# Expect:
# from render.composite_v2 import composite_scene_v2
# from render.assemble_v2 import assemble_concat, apply_ass_subtitle
```

→ Nếu worker đang dùng V2 → an toàn xóa V1.

### Files cần XÓA

```
render/composite.py            ← V1 legacy (drawtext, fade, _build_visual_filter)
render/assemble.py             ← V1 legacy (filter_complex re-encode)
render/subtitle_filter.py      ← drawtext chain (no longer used)
render/zoom_effect.py          ← V1 zoom (replaced by visual_fit.py)
voice/subtitle_builder.py      ← legacy fallback (no longer used)
ui/dialogs/voice_import.py     ← wizard (replaced by Process voice button)
```

→ Xác nhận xóa từng file:

```powershell
cd D:\Projects\story_video_making

# Backup trước khi xóa (just in case)
mkdir backup_legacy -ErrorAction SilentlyContinue
Copy-Item render\composite.py backup_legacy\
Copy-Item render\assemble.py backup_legacy\
Copy-Item render\subtitle_filter.py backup_legacy\
Copy-Item render\zoom_effect.py backup_legacy\
Copy-Item voice\subtitle_builder.py backup_legacy\
Copy-Item ui\dialogs\voice_import.py backup_legacy\

# Then delete
Remove-Item render\composite.py
Remove-Item render\assemble.py
Remove-Item render\subtitle_filter.py
Remove-Item render\zoom_effect.py
Remove-Item voice\subtitle_builder.py
Remove-Item ui\dialogs\voice_import.py
```

→ Sau đó verify nothing else imports từ những file này:

```powershell
Select-String -Recurse -Path *.py -Pattern "from render.composite import|from render.assemble import|from render.subtitle_filter|from render.zoom_effect|from voice.subtitle_builder|from ui.dialogs.voice_import"

# Expect: 0 results (mọi import đã được clean)
```

---

## CHANGE 8: Rename V2 → main

### File renames

```
render/composite_v2.py    →    render/composite.py
render/assemble_v2.py     →    render/assemble.py
```

→ Function rename:
- `composite_scene_v2` → `composite_scene`
- (assemble_v2 functions giữ nguyên tên)

### Update imports

```powershell
# Find all imports
Select-String -Recurse -Path *.py -Pattern "composite_v2|assemble_v2"

# Replace in all matched files:
# - "from render.composite_v2 import composite_scene_v2" → "from render.composite import composite_scene"
# - "composite_scene_v2(" → "composite_scene("
# - "from render.assemble_v2 import" → "from render.assemble import"
```

Files cần update:
- `workers/render_worker.py`
- Bất kỳ file nào khác import V2

### Verify

```powershell
# Verify NO references to v2
Select-String -Recurse -Path *.py -Pattern "_v2"
# Expect 0 results
```

---

## Build order

```
Day 1 (3h): Cleanup + UI
1. CHANGE 7: Cleanup V1 redundancy (30 phút)
2. CHANGE 8: Rename V2 → main (15 phút)
3. CHANGE 1: scenes_edited.json clone (1h)
4. CHANGE 2: Bỏ wizard voice_import (30 phút)
5. CHANGE 3: UI Review dialog 2-column (1.5h)
COMMIT 1: "cleanup + scenes_edited + UI redesign"

Day 2 (3h): Render fixes
6. CHANGE 4: Fix zoom jitter image_grok (30 phút)
7. CHANGE 5: Fix slideshow trắng + video zoom jitter (30 phút)
8. CHANGE 6: Voice-led timeline với freeze pause (1.5h)
9. Test E2E full (30 phút)
COMMIT 2: "render fix: smooth zoom + voice-led timeline"
```

**Total: ~6h**

---

## Test E2E Plan

### Setup

```powershell
cd D:\Projects\story_video_making\test_live

# Clear stale renders
Remove-Item renders\*.mp4 -ErrorAction SilentlyContinue
Remove-Item final.mp4 -ErrorAction SilentlyContinue
Remove-Item final.ass -ErrorAction SilentlyContinue
Remove-Item voice_mapping.json -ErrorAction SilentlyContinue
```

### Test sequence

```
1. Open app → load test_live
   ✓ scenes_edited.json auto-created
   ✓ App reads from scenes_edited.json
   ✓ Button "Reset to design" present

2. Click "Process voice" (NO wizard)
   ✓ Plan D alignment runs
   ✓ Review dialog opens with 2-column layout

3. Verify dialog
   ✓ 📜 Script left, Render duration right
   ✓ 🎤 Voice left, Voice timing right  
   ✓ Match score color-coded
   ✓ Move HEAD/TAIL buttons
   ✓ Render mode dropdown

4. Click Save → close dialog
   ✓ voice_mapping.json saved with freeze_pause_after fields

5. Click Render final
   ✓ Composite each scene OK (no errors)
   ✓ Assemble concat OK
   ✓ ASS apply OK

6. Inspect renders/SCENE-XX.mp4
   ✓ SCENE-01 (video_grok, no_effect): bitrate normal, video plays + freeze frame ending
   ✓ SCENE-02 (video_grok, zoom_out): smooth zoom (NO jitter)
   ✓ SCENE-03 (slideshow, zoom_out): NOT WHITE (bitrate > 1Mbps)
   ✓ SCENE-04 (video_grok, no_effect): plays correctly
   ✓ SCENE-05 (image_grok, zoom_out): smooth zoom (NO jitter)

7. Play final.mp4
   ✓ Karaoke white → yellow per word
   ✓ Subtitle position bottom center
   ✓ Each scene visual KHÔNG bị cắt thái quá
   ✓ Pause giữa scenes natural (freeze frame)
   ✓ Total duration = sum of (voice + freeze) per scene
```

---

## Critical reminders

1. **Verify worker dùng V2 trước khi xóa V1** (Change 7) — nếu worker vẫn dùng V1, app sẽ break
2. **Backup trước khi xóa** files legacy (`backup_legacy/`)
3. **Test sau MỖI commit** — không skip
4. **freeze_pause_after = 0** cho scene cuối cùng (no pause after last)
5. **Pre-scale 4x** apply cho cả image lẫn video path (Change 4 + 5)
6. **`d=total_frames` cho image, `d=1` cho video** (Change 4 vs 5)

---

## Confirm trước khi code

- [ ] Backup commit hiện tại
- [ ] Worker `render_worker.py` đang dùng V2 (verify trước cleanup)
- [ ] Test data test_live đầy đủ
- [ ] FFmpeg + libass + libx264 ready
- [ ] rapidfuzz installed (cho realign_helper.py từ Phase 6)
- [ ] pysubs2 installed (cho ass_generator)
