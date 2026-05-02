# Sprint 3 — Render Fix + UI Redesign

> **Goal**: Fix 4 issues còn lại sau Phase 6.
> **Scope**: Render only (zoom filter + slideshow composite). Voice align đã OK.
> **Effort**: ~3-4h

---

## Issues cần fix

| # | Issue | Module liên quan | Severity |
|---|---|---|---|
| 1 | Karaoke màu ngược (đang vàng → trắng, đáng lẽ trắng → vàng) | `voice/ass_generator.py` | LOW (1 dòng) |
| 2 | UI dialog Review verbose, cần compact 2-column | `ui/dialogs/voice_align_review.py` | MEDIUM |
| 3 | Zoom_in chưa áp dụng cho image/video scenes | `render/visual_fit.py` (hoặc tương tự) | HIGH |
| 4 | SCENE-03 slideshow composite output toàn trắng (bitrate 18 Kbps) | `render/composite_v2.py` + slideshow path | HIGH |
| 5 | SCENE-05 zoom_out giật cục (frame jitter) | `render/visual_fit.py` zoompan expression | HIGH |

→ Voice align đã OK (5/5 PASS, 100% match score). KHÔNG động vào voice modules.

---

## FIX 1: Karaoke màu (1 dòng)

### File: `voice/ass_generator.py`

ASS karaoke logic:
- `PrimaryColour` = màu chữ **sau khi** karaoke fill (đã được "hát")
- `SecondaryColour` = màu chữ **trước khi** karaoke fill (chưa được "hát")

User yêu cầu:
- Chữ chưa hát: **WHITE** → `SecondaryColour = white`
- Chữ đang/đã hát: **YELLOW** → `PrimaryColour = yellow`

### Verify code hiện tại

Trong `voice/ass_generator.py`, tìm constants:

```python
# Common patterns:
ASS_PRIMARY_COLOR = ...
ASS_SECONDARY_COLOR = ...
```

Hoặc trong `style.primarycolor = ...` / `style.secondarycolor = ...`.

### Fix

```python
# CŨ (sai):
ASS_PRIMARY_COLOR = (255, 255, 255)    # white
ASS_SECONDARY_COLOR = (255, 255, 0)    # yellow

# MỚI (đúng):
ASS_PRIMARY_COLOR = (255, 255, 0)      # YELLOW (chữ đã/đang được hát)
ASS_SECONDARY_COLOR = (255, 255, 255)  # WHITE (chữ chưa được hát)
```

→ Chỉ swap 2 dòng. Không cần thay đổi gì khác.

### Test

Render 1 scene → play final.mp4 → verify:
- Chữ ban đầu hiển thị trắng
- Highlight chạy từ trái sang phải, từng chữ chuyển sang vàng

---

## FIX 2: UI dialog Review redesign

### File: `ui/dialogs/voice_align_review.py`

### Layout mới (compact 2-column)

```
╔══════════════════════════════════════════════════════════════════════╗
║ SCENE-02                                  Match: 100% (deterministic)║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║  📜 Script (designed)              │  Render: [voice ▼] [5.84s ▲▼]  ║
║  ┌──────────────────────────────┐  │  Design: 5.0s                  ║
║  │ A barista wipes the counter  │  │                                ║
║  │ slowly. Steam curls from a   │  │                                ║
║  │ fresh espresso.              │  │                                ║
║  └──────────────────────────────┘  │                                ║
║                                     │                                ║
║  🎤 Voice (transcribed + cut)      │  ⏱ 7.38 → 13.22s              ║
║  ┌──────────────────────────────┐  │  Duration: 5.84s               ║
║  │ A barista wipes the counter  │  │                                ║
║  │ slowly. Steam curls from a   │  │                                ║
║  │ fresh espresso,              │  │                                ║
║  └──────────────────────────────┘  │                                ║
║                                                                       ║
║  [◀ Move HEAD up to SCENE-01]    [Move TAIL down to SCENE-03 ▶]      ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Implementation

```python
"""
Voice align review dialog — compact 2-column layout.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QFrame, QScrollArea, QWidget,
    QTextEdit, QSizePolicy,
)
from PyQt6.QtGui import QColor, QFont
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
        self.resize(1100, 700)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        stats = self.voice_mapping.get("stats", {})
        header = QLabel(
            f"<b>Plan D alignment</b> — scenes: {len(self.voice_mapping.get('scenes', []))} | "
            f"deterministic: {stats.get('deterministic_pass', 0)} | "
            f"LLM fallback: {stats.get('llm_fallback_count', 0)} | "
            f"silent: {stats.get('silent', 0)} | "
            f"voice files: {len(self.voice_mapping.get('voice_files', []))}"
        )
        layout.addWidget(header)
        
        # Scene list scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        self.scenes_container = QWidget()
        scenes_layout = QVBoxLayout(self.scenes_container)
        scenes_layout.setSpacing(6)
        
        for vs in self.voice_mapping.get("scenes", []):
            row = self._build_scene_row(vs)
            scenes_layout.addWidget(row)
        
        scenes_layout.addStretch()
        scroll.setWidget(self.scenes_container)
        layout.addWidget(scroll)
        
        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_re_align = QPushButton("Re-align all (rerun Plan D)")
        btn_re_align.clicked.connect(self._on_re_align)
        btn_row.addWidget(btn_re_align)
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
        """Build 1 scene row với 2-column layout."""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("""
            QFrame { border: 1px solid #ccc; border-radius: 4px; padding: 8px; }
            QTextEdit { background: #fafafa; border: 1px solid #ddd; }
        """)
        
        outer = QVBoxLayout(frame)
        outer.setSpacing(8)
        
        # === Top: Scene ID + Match score ===
        top_row = QHBoxLayout()
        scene_label = QLabel(f"<b style='font-size:11pt'>{vs['id']}</b>")
        top_row.addWidget(scene_label)
        top_row.addStretch()
        
        score = vs.get("score") or 0
        method = vs.get("method", "—")
        
        if vs.get("is_silent"):
            score_text = f"SILENT ({method})"
            color = "#888"
        else:
            color_key = "high" if score >= 90 else "medium" if score >= 70 else "low"
            color = SCORE_COLORS[color_key]
            score_text = f"Match: {score:.1f}% ({method})"
        
        score_label = QLabel(score_text)
        score_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        top_row.addWidget(score_label)
        
        outer.addLayout(top_row)
        
        # Skip middle for silent scenes
        if vs.get("is_silent"):
            silent_label = QLabel("<i>Silent scene — keeps design duration</i>")
            silent_label.setStyleSheet("color: #888; padding: 6px;")
            outer.addWidget(silent_label)
            return frame
        
        # === Middle: 2-column layout ===
        # Left: Script + Voice text
        # Right: Render duration + Voice timing
        
        grid = QGridLayout()
        grid.setColumnStretch(0, 3)  # Left wider
        grid.setColumnStretch(1, 2)  # Right narrower
        grid.setSpacing(8)
        
        # ── Row 1: Script (left) + Render duration (right) ──
        script_label = QLabel("📜 <b>Script</b>")
        grid.addWidget(script_label, 0, 0)
        
        render_label = QLabel("Render duration")
        render_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        grid.addWidget(render_label, 0, 1)
        
        # Row 2: Script text + Render mode controls
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
        
        render_panel = self._build_render_panel(vs)
        grid.addWidget(render_panel, 1, 1)
        
        # ── Row 3: Voice (left) + Voice timing (right) ──
        voice_label = QLabel("🎤 <b>Voice</b>")
        grid.addWidget(voice_label, 2, 0)
        
        timing_label = QLabel("Voice timing")
        timing_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        grid.addWidget(timing_label, 2, 1)
        
        # Row 4: Voice text + Timing info
        voice_edit = QTextEdit()
        voice_edit.setPlainText(vs.get("matched_text", ""))
        voice_edit.setReadOnly(True)
        voice_edit.setMaximumHeight(70)
        voice_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid.addWidget(voice_edit, 3, 0)
        
        timing_panel = self._build_timing_panel(vs)
        grid.addWidget(timing_panel, 3, 1)
        
        outer.addLayout(grid)
        
        # === Bottom: Move buttons ===
        scene_idx = self._get_scene_index(scene_id)
        total_scenes = len(self.voice_mapping["scenes"])
        
        btn_row = QHBoxLayout()
        
        btn_move_head = QPushButton("◀ Move HEAD up to previous")
        btn_move_head.setEnabled(scene_idx > 0)
        btn_move_head.clicked.connect(
            lambda checked=False, sid=scene_id: self._on_move_head(sid)
        )
        btn_row.addWidget(btn_move_head)
        btn_row.addStretch()
        
        btn_move_tail = QPushButton("Move TAIL down to next ▶")
        btn_move_tail.setEnabled(scene_idx < total_scenes - 1)
        btn_move_tail.clicked.connect(
            lambda checked=False, sid=scene_id: self._on_move_tail(sid)
        )
        btn_row.addWidget(btn_move_tail)
        
        outer.addLayout(btn_row)
        
        return frame
    
    def _build_render_panel(self, vs: dict) -> QWidget:
        """Right panel for render duration mode + custom input."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Mode dropdown + custom spinbox
        mode_row = QHBoxLayout()
        
        mode_combo = QComboBox()
        mode_combo.addItems(["voice", "design", "custom"])
        current_mode = vs.get("render_mode", "voice")
        mode_combo.setCurrentText(current_mode)
        mode_combo.setObjectName(f"mode_{vs['id']}")
        mode_row.addWidget(mode_combo)
        
        custom_spin = QDoubleSpinBox()
        custom_spin.setRange(0.5, 60.0)
        custom_spin.setSuffix(" s")
        custom_spin.setSingleStep(0.5)
        current_custom = vs.get("custom_duration") or vs.get("duration_original", 5)
        custom_spin.setValue(current_custom)
        custom_spin.setObjectName(f"custom_{vs['id']}")
        custom_spin.setEnabled(current_mode == "custom")
        mode_row.addWidget(custom_spin)
        
        mode_combo.currentTextChanged.connect(
            lambda mode, spin=custom_spin: spin.setEnabled(mode == "custom")
        )
        
        layout.addLayout(mode_row)
        
        # Info: design vs voice duration
        design = vs.get("duration_original", 0)
        voice_dur = (vs.get("voice_out") or 0) - (vs.get("voice_in") or 0)
        
        info_label = QLabel(f"Design: {design}s")
        info_label.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(info_label)
        
        layout.addStretch()
        return panel
    
    def _build_timing_panel(self, vs: dict) -> QWidget:
        """Right panel for voice timing info."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        voice_in = vs.get("voice_in") or 0
        voice_out = vs.get("voice_out") or 0
        voice_dur = voice_out - voice_in
        
        timing_label = QLabel(f"⏱ {voice_in:.2f} → {voice_out:.2f}s")
        timing_label.setStyleSheet("font-family: monospace; font-size: 9pt;")
        layout.addWidget(timing_label)
        
        dur_label = QLabel(f"Duration: <b>{voice_dur:.2f}s</b>")
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
            from PyQt6.QtWidgets import QMessageBox
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
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Move TAIL failed", str(e))
    
    def _refresh_ui(self):
        """Rebuild scenes container content."""
        # Clear existing scene rows
        layout = self.scenes_container.layout()
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Rebuild
        for vs in self.voice_mapping.get("scenes", []):
            row = self._build_scene_row(vs)
            layout.addWidget(row)
        layout.addStretch()
    
    def _on_save(self):
        """Collect render_mode + custom_duration from UI, emit save signal."""
        for vs in self.voice_mapping["scenes"]:
            scene_id = vs["id"]
            mode_combo = self.findChild(QComboBox, f"mode_{scene_id}")
            custom_spin = self.findChild(QDoubleSpinBox, f"custom_{scene_id}")
            
            if mode_combo:
                vs["render_mode"] = mode_combo.currentText()
            if custom_spin and vs.get("render_mode") == "custom":
                vs["custom_duration"] = custom_spin.value()
            
            # Calculate render_duration based on mode
            if vs.get("is_silent"):
                vs["render_duration"] = vs.get("duration_original", 5)
            elif vs.get("render_mode") == "voice":
                vs["render_duration"] = (vs.get("voice_out") or 0) - (vs.get("voice_in") or 0)
            elif vs.get("render_mode") == "design":
                vs["render_duration"] = vs.get("duration_original", 5)
            else:  # custom
                vs["render_duration"] = vs.get("custom_duration", vs.get("duration_original", 5))
        
        self.save_requested.emit(self.voice_mapping)
        self.accept()
    
    def _on_re_align(self):
        self.done(2)
```

### Notes

- Voice timing và Render duration ở **bên phải** (consistent layout)
- Script và Voice text ở **bên trái** (text content)
- TextEdit có scroll khi text dài
- Move HEAD/TAIL buttons giữ ở dưới mỗi scene
- Silent scenes hiện nhỏ gọn, không có panel script/voice

---

## FIX 3, 4, 5: Render zoom + slideshow

### Vấn đề chính cần fix

| # | Issue | Module |
|---|---|---|
| 3 | Zoom_in chưa áp dụng | `render/visual_fit.py` |
| 4 | SCENE-03 slideshow output trắng (bitrate 18 Kbps) | `render/composite_v2.py` slideshow path |
| 5 | SCENE-05 zoom_out giật cục | `render/visual_fit.py` zoompan expression |

### Suspect code patterns

Trước khi fix, Claude Code cần **inspect** các file:
- `render/visual_fit.py` (hoặc tương tự có function `build_zoom_filter`)
- `render/composite_v2.py` slideshow handling
- Bất kỳ module nào có `zoompan` filter

### Fix zoompan expression (Issue 5)

Bug pattern phổ biến:

```python
# ❌ BUG: zoom expression KHÔNG liên tục
zoom_filter = f"zoompan=z='if(eq(on,0),1.2,zoom-{step})':d={frames}:s=1920x1080:fps=30"
# `on` trong zoompan reset mỗi frame group → zoom reset → giật
```

Fix đúng:

```python
# ✅ FIX: dùng frame counter `on` linear thay vì incremental
def build_zoom_filter(effect: str, duration_sec: float, fps: int = 30,
                     width: int = 1920, height: int = 1080) -> str:
    """Build zoompan filter with smooth linear interpolation."""
    
    if effect == "no_effect":
        return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    
    total_frames = int(duration_sec * fps)
    zoom_max = 1.2
    zoom_min = 1.0
    
    if effect == "zoom_in":
        # Linear interpolation: zoom from 1.0 → 1.2 over total_frames
        # `on` is the current output frame (0 to total_frames-1)
        z_expr = f"{zoom_min}+({zoom_max}-{zoom_min})*on/{total_frames}"
    elif effect == "zoom_out":
        # Linear: zoom from 1.2 → 1.0
        z_expr = f"{zoom_max}-({zoom_max}-{zoom_min})*on/{total_frames}"
    else:
        return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    
    return (
        f"zoompan=z='{z_expr}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:"  # Critical: d=1 means each input frame produces 1 output frame
        f"s={width}x{height}:fps={fps},"
        f"setsar=1"
    )
```

**Key fix**: 
- `d=1` (mỗi input frame → 1 output frame) thay vì `d=total_frames` (1 input → many outputs)
- Dùng `on` linear (frame counter của OUTPUT) cho smooth interpolation
- Không dùng `if(eq(on,0),...)` reset

### Fix slideshow composite (Issue 4)

Slideshow visual_type = `slideshow` → input là **video file** (vid3.mp4), không phải image.

Composite code cần handle khác image_grok:

```python
# ❌ BUG patterns (có thể):
# 1. Treating slideshow as image (loop=1) → static white frame
# 2. Apply zoompan on video input incorrectly
# 3. Wrong fps/setpts conversion

# ✅ FIX: slideshow = video input, treat like video_grok
def build_slideshow_filter(duration_design, duration_render, effect):
    """
    Slideshow input = pre-rendered video (vid3.mp4).
    Logic giống video_grok:
    - duration_render < duration_design → setpts speedup
    - duration_render > duration_design → tpad freeze last frame
    - duration_render == duration_design → no fit
    """
    parts = []
    
    if abs(duration_render - duration_design) < 0.1:
        # No fit needed
        pass
    elif duration_render < duration_design:
        # Speedup
        pts_factor = duration_render / duration_design
        parts.append(f"setpts={pts_factor:.4f}*PTS")
    else:
        # Extend
        extra = duration_render - duration_design
        parts.append(f"tpad=stop_mode=clone:stop_duration={extra:.3f}")
    
    # Add zoom effect on TOP of speedup/extend
    if effect != "no_effect":
        zoom_part = build_zoom_filter(effect, duration_render)
        parts.append(zoom_part)
    else:
        # Just scale + pad
        parts.append(f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
    
    return ",".join(parts)
```

**Critical**:
- Slideshow input MUST be treated as VIDEO (no `-loop 1`)
- ffmpeg input args: `-i {vid3_path}` (KHÔNG `-loop 1 -i ...`)
- Filter chain: setpts/tpad TRƯỚC, zoompan SAU (nếu có)

### Fix composite_v2.py for slideshow

```python
def composite_scene(scene, voice_scene, visual_path, voice_files, project_root, output_path):
    # ...
    visual_type = scene["visual_type"]
    
    # Visual input args
    if visual_type in ("image_grok",):
        # Static image, loop
        visual_input = ["-loop", "1", "-i", str(visual_path)]
    else:
        # Video file (video_grok, slideshow, ken_burns_*)
        visual_input = ["-i", str(visual_path)]
    
    # Build visual filter
    if visual_type in ("image_grok",):
        # zoompan on still image
        visual_filter = build_zoom_filter(
            effect=scene.get("effect", "no_effect"),
            duration_sec=render_duration,
        )
    elif visual_type == "slideshow":
        # Pre-rendered video, fit duration + optional zoom
        visual_filter = build_slideshow_filter(
            duration_design=duration_design,
            duration_render=render_duration,
            effect=scene.get("effect", "no_effect"),
        )
    elif visual_type == "video_grok":
        # Same as slideshow for filter chain
        visual_filter = build_slideshow_filter(  # rename later: build_video_filter
            duration_design=duration_design,
            duration_render=render_duration,
            effect=scene.get("effect", "no_effect"),
        )
    
    # ... rest of composite logic
```

### Test pattern

```bash
# 1. Render single scene
python -c "
from render.composite_v2 import composite_scene
# ... setup args ...
composite_scene(...)
"

# 2. Inspect output
ffprobe -v error D:\Projects\story_video_making\test_live\renders\SCENE-03.mp4 \
  -show_format | grep bit_rate

# Expected: bit_rate > 1000000 (1 Mbps+, có nội dung)
# Bug if: bit_rate < 50000 (toàn trắng)
```

---

## File modifications summary

| File | Change | Effort |
|---|---|---|
| `voice/ass_generator.py` | Swap PRIMARY ↔ SECONDARY color | 5 phút |
| `ui/dialogs/voice_align_review.py` | Rewrite layout 2-column | 1.5h |
| `render/visual_fit.py` | Fix zoompan expression smooth (no jitter) | 30 phút |
| `render/composite_v2.py` | Fix slideshow path (treat as video, not image) | 30 phút |
| Build slideshow filter helper | NEW function | 30 phút |

**Total: ~3-4h**

---

## Test plan after fix

### Test 1: Karaoke màu

```
1. Render bất kỳ scene
2. Play final.mp4
3. Verify:
   ✓ Chữ ban đầu hiển thị WHITE
   ✓ Karaoke chạy từ trái → phải
   ✓ Mỗi từ chuyển từ WHITE → YELLOW khi đến lượt
```

### Test 2: UI dialog

```
1. Click "Process voice"
2. Dialog mở với layout 2-column
3. Verify:
   ✓ Script bên trái + Render duration bên phải
   ✓ Voice bên trái + Voice timing bên phải
   ✓ Match score color-coded ở góc trên phải mỗi scene
   ✓ Move HEAD/TAIL buttons ở dưới
   ✓ Text scrollable nếu dài
```

### Test 3: Zoom direction

```
1. Edit scenes.json: SCENE-X effect = "zoom_in"
2. Render
3. Play SCENE-X.mp4
4. Verify zoom_in: bắt đầu xa, kết thúc gần
5. Test zoom_out: bắt đầu gần, kết thúc xa
```

### Test 4: SCENE-03 slideshow

```
1. Render full
2. Inspect renders/SCENE-03.mp4:
   - bit_rate > 1 Mbps (KHÔNG phải 18 Kbps)
   - Frames có nội dung (cup, notebook)
3. Play final.mp4 → SCENE-03 phải hiển thị slideshow đúng
```

### Test 5: SCENE-05 smooth zoom_out

```
1. Render SCENE-05
2. Play renders/SCENE-05.mp4 chậm (0.5x speed)
3. Verify:
   ✓ Zoom liên tục, không giật
   ✓ Camera mở rộng dần (zoom_out)
```

---

## Build order

1. **Fix 1 (karaoke màu)** — 5 phút
   - Swap colors trong ass_generator.py
   - Test: render 1 scene, verify visual

2. **Fix 5 (zoompan jitter)** — 30 phút  
   - Update build_zoom_filter trong visual_fit.py
   - Use linear interpolation `on/total_frames`
   - Test: render SCENE-05 zoom_out smooth

3. **Fix 3 (zoom_in direction)** — auto fix sau Fix 5
   - Fix 5 đã rewrite expression đúng cho cả zoom_in/out
   - Test: render scene zoom_in, verify direction

4. **Fix 4 (slideshow trắng)** — 1h
   - Inspect composite_v2.py current handling
   - Add slideshow path: treat as video file
   - Build slideshow filter helper
   - Test: render SCENE-03, verify bitrate + visual

5. **Fix 2 (UI redesign)** — 1.5h
   - Rewrite voice_align_review.py
   - Test: open dialog, verify layout

6. **E2E test** — 30 phút
   - Clear renders/ + final.mp4
   - Re-render full
   - Verify 5 scenes pass tests 1-5

7. **Commit** — "Sprint 3 final fixes: karaoke color + UI redesign + zoom filter + slideshow render"

---

## Confirm trước khi code

- [ ] Phase 6 đã commit (render worker wired Plan D)
- [ ] Voice align test pass 100%
- [ ] Test data test_live đầy đủ (vid1-5, voice1.mp3, scenes.json)
- [ ] Backup commit hiện tại trước khi fix
- [ ] FFmpeg + libass + libx264 ready

→ Build sequential, test sau mỗi fix. STOP nếu test fail bất kỳ step nào.
