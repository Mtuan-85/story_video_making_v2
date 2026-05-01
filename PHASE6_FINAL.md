# Phase 6 — Wire Render + Review Dialog Manual Realign

> **Goal**: Wire Plan D render path + UI dialog cho user fix voice mismatch + render duration override.
> **Scope**: 3 features. Effort ~3-4h.
> **Status sau Verify**: Plan D Phase 1-5 đã DONE. Chỉ còn Phase 6 này.

---

## 3 Features cần build

### Feature 1: Wire render worker → Plan D code (CRITICAL)

`workers/render_worker.py` hiện tại import:
- `render.assemble` (drawtext path)
- `render.composite` (drawtext path)

→ Phải đổi sang:
- `render.assemble_v2` (libass apply ASS)
- `render.composite_v2` (no subtitle in composite)
- `voice.ass_generator.generate_final_ass` (gen ASS trước assemble)

### Feature 2: Update Review Voice Alignment dialog

UI mới hiển thị:
- Script (read-only)
- Voice text matched (read-only)
- Match score color-coded
- 2 button Move HEAD/TAIL
- Render duration mode dropdown
- Bỏ spinbox voice_in/voice_out
- Bỏ phase grouping (đã không có v4.0)
- Bỏ button "Re-align with hint"

### Feature 3: Render duration override

User chọn duration cho mỗi scene:
- `voice` (default, render = voice duration)
- `design` (render = scenes.json duration, voice padded silence cuối)
- `custom` (user input số giây)

Render logic update để pad silence khi render > voice.

---

## Feature 1: Wire render worker

### File: `workers/render_worker.py`

Đổi imports + logic:

```python
# BEFORE (legacy):
from render.composite import composite_scene
from render.assemble import assemble_concat

# AFTER (Plan D):
from render.composite_v2 import composite_scene  # no subtitle
from render.assemble_v2 import assemble_concat, apply_ass_subtitle
from voice.ass_generator import generate_final_ass
```

### Run logic mới (2-pass)

```python
async def run(self):
    try:
        scenes = self.project.scenes_json.scenes
        voice_scenes = self.voice_mapping["scenes"]
        voice_files = self.voice_mapping["voice_files"]
        project_root = self.project.paths.root
        renders_dir = project_root / "renders"
        renders_dir.mkdir(exist_ok=True)
        
        total = len(scenes)
        
        # === PASS 1: Composite each scene (NO subtitle) ===
        scene_paths = []
        for i, scene_obj in enumerate(scenes):
            scene_id = scene_obj.id
            
            vs = next((s for s in voice_scenes if s["id"] == scene_id), None)
            if not vs:
                log.error(f"{scene_id}: not in voice_mapping, skip")
                continue
            
            visual_path = self._get_visual_path(scene_obj)
            if not visual_path or not visual_path.exists():
                log.error(f"{scene_id}: visual not found, skip")
                continue
            
            self.progress_update.emit(i + 1, total, f"Composite {scene_id}...")
            
            output = renders_dir / f"{scene_id}.mp4"
            composite_scene(
                scene=scene_obj.model_dump(),
                voice_scene=vs,
                visual_path=visual_path,
                voice_files=voice_files,
                project_root=project_root,
                output_path=output,
            )
            scene_paths.append(output)
        
        # === PASS 2: Assemble concat ===
        self.progress_update.emit(total, total, "Assembling...")
        final_raw = project_root / "final_raw.mp4"
        assemble_concat(scene_paths, final_raw)
        
        # === PASS 3: Generate final.ass ===
        self.progress_update.emit(total, total, "Generating subtitles...")
        ass_path = project_root / "final.ass"
        generate_final_ass(
            voice_mapping=self.voice_mapping,
            output_path=ass_path,
            video_width=1920,    # match composite output
            video_height=1080,
        )
        
        # === PASS 4: Apply ASS to final_raw → final.mp4 ===
        self.progress_update.emit(total, total, "Applying subtitles...")
        final_path = project_root / "final.mp4"
        apply_ass_subtitle(final_raw, ass_path, final_path)
        
        # Cleanup intermediate
        try:
            final_raw.unlink()
        except Exception:
            pass
        
        self.render_done.emit(str(final_path))
    
    except Exception as e:
        log.error(f"Render failed: {e}")
        self.render_failed.emit(str(e))
```

### Verify ASS apply không lỗi path

`apply_ass_subtitle()` cần escape path Windows:

```python
ass_safe = str(ass_path.resolve()).replace("\\", "/")
ass_safe = ass_safe.replace(":", "\\:")
# vf = f"subtitles='{ass_safe}'"
```

→ Nếu code v2 đã có thì OK. Nếu chưa, add.

---

## Feature 2: Review Dialog mới

### File: `ui/dialogs/voice_align_review.py` — REWRITE

Layout mới (per scene):

```
╔══════════════════════════════════════════════════════════════════════╗
║ SCENE-02                                          Match: ████ 98%    ║
╠══════════════════════════════════════════════════════════════════════╣
║ Script:                                                               ║
║ "A barista wipes the counter slowly. Steam curls from a fresh         ║
║  espresso."                                                           ║
║                                                                       ║
║ Voice:                                                                ║
║ "A barista wipes the counter slowly. Steam curls from a fresh         ║
║  espresso, three small things on the"                                 ║
║ (7.36 - 13.22s, 5.86s)                                               ║
║                                                                       ║
║ Render duration: [voice ▼]    Design: 5s | Voice: 5.86s              ║
║                                                                       ║
║ [◀ Move HEAD up to SCENE-01]    [Move TAIL down to SCENE-03 ▶]       ║
╚══════════════════════════════════════════════════════════════════════╝
```

### Code skeleton

```python
"""
Voice align review dialog with manual realign features.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QFrame, QScrollArea, QWidget,
    QTextEdit,
)
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtCore import Qt, pyqtSignal


SCORE_COLORS = {
    "high": "#2e7d32",      # green ≥ 90
    "medium": "#f57c00",    # orange 70-89
    "low": "#c62828",       # red < 70
}


class VoiceAlignReviewDialog(QDialog):
    save_requested = pyqtSignal(dict)  # voice_mapping
    
    def __init__(self, voice_mapping: dict, scenes_data: list, whisper_words: list, parent=None):
        super().__init__(parent)
        self.voice_mapping = voice_mapping
        self.scenes_data = scenes_data  # for script_en lookup
        self.whisper_words = whisper_words  # for move/recalculate
        
        self.setWindowTitle("Voice Alignment Review")
        self.resize(1100, 750)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        stats = self.voice_mapping.get("stats", {})
        header = QLabel(
            f"<b>Voice files: {len(self.voice_mapping.get('voice_files', []))}</b>  |  "
            f"Total: {len(self.voice_mapping.get('scenes', []))} scenes  |  "
            f"Deterministic: {stats.get('deterministic_pass', 0)}  |  "
            f"LLM: {stats.get('llm_fallback_count', 0)}  |  "
            f"Silent: {stats.get('silent', 0)}"
        )
        layout.addWidget(header)
        
        # Scrollable scene list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        
        for vs in self.voice_mapping.get("scenes", []):
            row = self._build_scene_row(vs)
            container_layout.addWidget(row)
        
        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        # Buttons
        btn_row = QHBoxLayout()
        
        btn_re_align = QPushButton("🔄 Re-align all (rerun Plan D)")
        btn_re_align.clicked.connect(self._on_re_align)
        btn_row.addWidget(btn_re_align)
        
        btn_row.addStretch()
        
        btn_save = QPushButton("💾 Save")
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)
        
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        
        layout.addLayout(btn_row)
    
    def _build_scene_row(self, vs: dict) -> QFrame:
        """Build 1 scene row (frame)."""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("QFrame { border: 1px solid #ccc; padding: 8px; margin: 4px; }")
        
        layout = QVBoxLayout(frame)
        
        # Scene header với match score
        header = QHBoxLayout()
        scene_label = QLabel(f"<b>{vs['id']}</b>")
        header.addWidget(scene_label)
        
        score = vs.get("score", 0) or 0
        method = vs.get("method", "—")
        
        if vs.get("is_silent"):
            score_text = f"SILENT ({method})"
            color = "#999"
        else:
            color_key = "high" if score >= 90 else "medium" if score >= 70 else "low"
            color = SCORE_COLORS[color_key]
            score_text = f"Match: {score:.1f}% ({method})"
        
        score_label = QLabel(score_text)
        score_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        header.addStretch()
        header.addWidget(score_label)
        layout.addLayout(header)
        
        # Script (read-only)
        if not vs.get("is_silent"):
            scene_id = vs["id"]
            script_text = next(
                (s["story_en"] for s in self.scenes_data if s["id"] == scene_id),
                "",
            )
            
            script_label = QLabel("<b>Script:</b>")
            layout.addWidget(script_label)
            
            script_view = QTextEdit()
            script_view.setPlainText(script_text)
            script_view.setReadOnly(True)
            script_view.setMaximumHeight(60)
            layout.addWidget(script_view)
            
            # Voice text matched
            voice_label = QLabel("<b>Voice:</b>")
            layout.addWidget(voice_label)
            
            voice_view = QTextEdit()
            voice_text = vs.get("matched_text", "")
            voice_in = vs.get("voice_in", 0)
            voice_out = vs.get("voice_out", 0)
            voice_dur = voice_out - voice_in
            
            voice_view.setPlainText(
                f"{voice_text}\n\n"
                f"({voice_in:.2f}-{voice_out:.2f}s, {voice_dur:.2f}s)"
            )
            voice_view.setReadOnly(True)
            voice_view.setMaximumHeight(80)
            layout.addWidget(voice_view)
        
        # Render duration mode
        render_row = QHBoxLayout()
        render_row.addWidget(QLabel("Render duration:"))
        
        mode_combo = QComboBox()
        mode_combo.addItems(["voice", "design", "custom"])
        current_mode = vs.get("render_mode", "voice")
        mode_combo.setCurrentText(current_mode)
        mode_combo.setObjectName(f"mode_{vs['id']}")
        render_row.addWidget(mode_combo)
        
        custom_spin = QDoubleSpinBox()
        custom_spin.setRange(0.5, 60.0)
        custom_spin.setSuffix(" s")
        custom_spin.setSingleStep(0.5)
        current_custom = vs.get("custom_duration") or vs.get("duration_original", 5)
        custom_spin.setValue(current_custom)
        custom_spin.setObjectName(f"custom_{vs['id']}")
        custom_spin.setEnabled(current_mode == "custom")
        render_row.addWidget(custom_spin)
        
        # Enable/disable custom_spin theo mode
        mode_combo.currentTextChanged.connect(
            lambda mode, spin=custom_spin: spin.setEnabled(mode == "custom")
        )
        
        # Info labels
        design = vs.get("duration_original", 0)
        voice_dur = (vs.get("voice_out") or 0) - (vs.get("voice_in") or 0) if not vs.get("is_silent") else design
        info_label = QLabel(f"Design: {design}s | Voice: {voice_dur:.2f}s")
        info_label.setStyleSheet("color: #666;")
        render_row.addWidget(info_label)
        render_row.addStretch()
        
        layout.addLayout(render_row)
        
        # Move buttons (only if not silent and not first/last)
        if not vs.get("is_silent"):
            btn_row = QHBoxLayout()
            
            scene_idx = self._get_scene_index(vs["id"])
            
            btn_move_head = QPushButton("◀ Move HEAD up to previous")
            btn_move_head.setEnabled(scene_idx > 0)
            btn_move_head.clicked.connect(
                lambda checked=False, sid=vs["id"]: self._on_move_head(sid)
            )
            btn_row.addWidget(btn_move_head)
            
            btn_row.addStretch()
            
            btn_move_tail = QPushButton("Move TAIL down to next ▶")
            btn_move_tail.setEnabled(scene_idx < len(self.voice_mapping["scenes"]) - 1)
            btn_move_tail.clicked.connect(
                lambda checked=False, sid=vs["id"]: self._on_move_tail(sid)
            )
            btn_row.addWidget(btn_move_tail)
            
            layout.addLayout(btn_row)
        
        return frame
    
    def _get_scene_index(self, scene_id: str) -> int:
        for i, vs in enumerate(self.voice_mapping["scenes"]):
            if vs["id"] == scene_id:
                return i
        return -1
    
    def _on_move_head(self, scene_id: str):
        """Move HEAD of this scene up to previous scene's tail."""
        from voice.realign_helper import move_head_to_previous
        try:
            updated = move_head_to_previous(
                voice_mapping=self.voice_mapping,
                scene_id=scene_id,
                whisper_words=self.whisper_words,
                scenes_data=self.scenes_data,
            )
            self.voice_mapping = updated
            self._refresh_ui()
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Move failed", str(e))
    
    def _on_move_tail(self, scene_id: str):
        """Move TAIL of this scene down to next scene's head."""
        from voice.realign_helper import move_tail_to_next
        try:
            updated = move_tail_to_next(
                voice_mapping=self.voice_mapping,
                scene_id=scene_id,
                whisper_words=self.whisper_words,
                scenes_data=self.scenes_data,
            )
            self.voice_mapping = updated
            self._refresh_ui()
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Move failed", str(e))
    
    def _refresh_ui(self):
        """Rebuild all scene rows."""
        # Clear existing layout, rebuild
        # Implementation: lưu QWidget container, clear, rebuild
        # ...
        pass
    
    def _on_save(self):
        """Collect render_mode + custom_duration from UI, save voice_mapping."""
        for vs in self.voice_mapping["scenes"]:
            scene_id = vs["id"]
            mode_combo = self.findChild(QComboBox, f"mode_{scene_id}")
            custom_spin = self.findChild(QDoubleSpinBox, f"custom_{scene_id}")
            
            if mode_combo:
                vs["render_mode"] = mode_combo.currentText()
            if custom_spin and vs.get("render_mode") == "custom":
                vs["custom_duration"] = custom_spin.value()
            
            # Calculate render_duration from mode
            if vs.get("is_silent"):
                vs["render_duration"] = vs.get("duration_original", 5)
            elif vs["render_mode"] == "voice":
                vs["render_duration"] = (vs["voice_out"] or 0) - (vs["voice_in"] or 0)
            elif vs["render_mode"] == "design":
                vs["render_duration"] = vs.get("duration_original", 5)
            else:  # custom
                vs["render_duration"] = vs.get("custom_duration", vs.get("duration_original", 5))
        
        self.save_requested.emit(self.voice_mapping)
        self.accept()
    
    def _on_re_align(self):
        """Trigger full re-run alignment."""
        self.done(2)
```

### Module mới: `voice/realign_helper.py`

```python
"""
Helper functions để move HEAD/TAIL between scenes.
"""

from rapidfuzz import fuzz
from loguru import logger as log


def move_tail_to_next(
    voice_mapping: dict,
    scene_id: str,
    whisper_words: list,
    scenes_data: list,
) -> dict:
    """
    Move tail of scene_id to next scene's head.
    
    Logic:
    1. Find current scene và next scene trong voice_mapping
    2. Identify đoạn "extra" ở cuối current (không match script)
    3. Update voice_out current, voice_in next
    4. Recalculate match scores
    """
    
    scenes = voice_mapping["scenes"]
    
    # Find current + next scene index
    cur_idx = next((i for i, s in enumerate(scenes) if s["id"] == scene_id), -1)
    if cur_idx < 0 or cur_idx >= len(scenes) - 1:
        raise ValueError(f"Cannot move tail: {scene_id} is last scene")
    
    cur = scenes[cur_idx]
    nxt = scenes[cur_idx + 1]
    
    if cur.get("is_silent"):
        raise ValueError(f"Cannot move from silent scene")
    
    # Get current script (from scenes_data)
    cur_script = next(
        (s.get("story_en", "") for s in scenes_data if s["id"] == scene_id),
        "",
    )
    
    if not cur_script:
        raise ValueError(f"Scene {scene_id} has no story_en")
    
    # Get word indices from voice_in/voice_out
    cur_words = _get_words_in_range(whisper_words, cur["voice_in"], cur["voice_out"])
    
    if len(cur_words) < 2:
        raise ValueError(f"Too few words to split")
    
    # Find best ending position: try shrinking from the end, find size with best match
    best_end = len(cur_words) - 1
    best_score = 0
    
    cur_script_norm = _normalize(cur_script)
    
    for end_idx in range(max(2, len(cur_words) // 2), len(cur_words)):
        candidate_text = " ".join(_normalize(w["word"]) for w in cur_words[:end_idx + 1])
        score = fuzz.ratio(cur_script_norm, candidate_text)
        if score > best_score:
            best_score = score
            best_end = end_idx
    
    # New voice_out for current = end of cur_words[best_end]
    new_cur_out = cur_words[best_end]["end"]
    
    # New voice_in for next = start of cur_words[best_end + 1] (or current voice_in if no extra)
    if best_end + 1 < len(cur_words):
        new_nxt_in = cur_words[best_end + 1]["start"]
    else:
        # No extra to move (already perfect match)
        log.info(f"{scene_id}: no extra to move, current already optimal")
        return voice_mapping
    
    # Update mappings
    cur["voice_out"] = new_cur_out
    cur["matched_text"] = " ".join(w["word"] for w in cur_words[:best_end + 1])
    cur["score"] = best_score
    
    # Next scene: extend voice_in earlier
    if not nxt.get("is_silent"):
        nxt["voice_in"] = new_nxt_in
        # Recalculate next's matched_text + score
        nxt_words = _get_words_in_range(whisper_words, new_nxt_in, nxt["voice_out"])
        nxt["matched_text"] = " ".join(w["word"] for w in nxt_words)
        nxt_script = next(
            (s.get("story_en", "") for s in scenes_data if s["id"] == nxt["id"]),
            "",
        )
        if nxt_script:
            nxt["score"] = fuzz.ratio(_normalize(nxt_script), _normalize(nxt["matched_text"]))
    
    log.info(f"Moved tail of {scene_id}: new voice_out={new_cur_out:.2f}, score={best_score:.1f}")
    return voice_mapping


def move_head_to_previous(
    voice_mapping: dict,
    scene_id: str,
    whisper_words: list,
    scenes_data: list,
) -> dict:
    """
    Move head of scene_id up to previous scene's tail.
    
    Logic similar to move_tail_to_next but reversed.
    """
    
    scenes = voice_mapping["scenes"]
    cur_idx = next((i for i, s in enumerate(scenes) if s["id"] == scene_id), -1)
    if cur_idx <= 0:
        raise ValueError(f"Cannot move head: {scene_id} is first scene")
    
    cur = scenes[cur_idx]
    prev = scenes[cur_idx - 1]
    
    if cur.get("is_silent"):
        raise ValueError(f"Cannot move from silent scene")
    
    cur_script = next(
        (s.get("story_en", "") for s in scenes_data if s["id"] == scene_id),
        "",
    )
    if not cur_script:
        raise ValueError(f"Scene {scene_id} has no story_en")
    
    cur_words = _get_words_in_range(whisper_words, cur["voice_in"], cur["voice_out"])
    if len(cur_words) < 2:
        raise ValueError(f"Too few words to split")
    
    # Find best starting position: shrink from start, find best match
    best_start = 0
    best_score = 0
    cur_script_norm = _normalize(cur_script)
    
    for start_idx in range(0, len(cur_words) // 2):
        candidate_text = " ".join(_normalize(w["word"]) for w in cur_words[start_idx:])
        score = fuzz.ratio(cur_script_norm, candidate_text)
        if score > best_score:
            best_score = score
            best_start = start_idx
    
    if best_start == 0:
        log.info(f"{scene_id}: no extra at head to move")
        return voice_mapping
    
    new_cur_in = cur_words[best_start]["start"]
    new_prev_out = cur_words[best_start - 1]["end"]
    
    cur["voice_in"] = new_cur_in
    cur["matched_text"] = " ".join(w["word"] for w in cur_words[best_start:])
    cur["score"] = best_score
    
    if not prev.get("is_silent"):
        prev["voice_out"] = new_prev_out
        prev_words = _get_words_in_range(whisper_words, prev["voice_in"], new_prev_out)
        prev["matched_text"] = " ".join(w["word"] for w in prev_words)
        prev_script = next(
            (s.get("story_en", "") for s in scenes_data if s["id"] == prev["id"]),
            "",
        )
        if prev_script:
            prev["score"] = fuzz.ratio(_normalize(prev_script), _normalize(prev["matched_text"]))
    
    log.info(f"Moved head of {scene_id}: new voice_in={new_cur_in:.2f}, score={best_score:.1f}")
    return voice_mapping


def _get_words_in_range(whisper_words: list, voice_in: float, voice_out: float) -> list:
    return [
        w for w in whisper_words
        if voice_in <= w["start"] and w["end"] <= voice_out
    ]


def _normalize(text: str) -> str:
    import re
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return text
```

---

## Feature 3: Render duration override

### Schema voice_mapping update

Thêm fields per scene:

```json
{
  "id": "SCENE-03",
  "voice_in": 13.76,
  "voice_out": 19.74,
  "duration_original": 10,
  "duration_adjusted": 5.98,
  "render_duration": 5.98,
  "render_mode": "voice",
  "custom_duration": null,
  "is_silent": false,
  ...
}
```

→ `render_mode`: voice / design / custom
→ `render_duration`: actual duration để render (computed from mode)
→ `custom_duration`: chỉ dùng khi mode = custom

### Update `render/composite_v2.py`

Use `render_duration` thay vì `duration_adjusted`:

```python
def composite_scene(scene, voice_scene, visual_path, voice_files, project_root, output_path):
    render_dur = voice_scene.get("render_duration") or voice_scene.get("duration_adjusted")
    voice_dur = (voice_scene.get("voice_out") or 0) - (voice_scene.get("voice_in") or 0) if not voice_scene.get("is_silent") else 0
    design_dur = voice_scene["duration_original"]
    
    visual_type = scene["visual_type"]
    effect = scene.get("effect", "no_effect")
    
    # Visual filter: stretch/speedup theo render_dur (KHÔNG phải voice_dur)
    visual_filter = build_visual_filter_with_fit(
        visual_type, design_dur, render_dur, effect
    )
    
    # Audio: voice slice + silence padding nếu render > voice
    if voice_scene.get("is_silent") or voice_dur <= 0:
        audio_input, audio_filter = get_silent_audio_args(render_dur)
    else:
        audio_input, audio_filter, concat_list = get_voice_slice_args(
            voice_files=voice_files,
            voice_in=voice_scene["voice_in"],
            voice_out=voice_scene["voice_out"],
            project_root=project_root,
        )
        
        # Add silence padding if render > voice
        if render_dur > voice_dur:
            pad_dur = render_dur - voice_dur
            audio_filter = f"{audio_filter},apad=pad_dur={pad_dur:.3f}"
    
    # ... rest of ffmpeg command
    # -t {render_dur}  ← cap output duration
```

### Update `voice/ass_generator.py`

ASS timing dùng `render_duration` (cumulative) thay vì `duration_adjusted`:

```python
cursor_ms = 0
for vs in voice_mapping["scenes"]:
    scene_dur_ms = int((vs.get("render_duration") or vs.get("duration_adjusted")) * 1000)
    
    if vs.get("is_silent") or not vs.get("subtitle_phrases"):
        cursor_ms += scene_dur_ms
        continue
    
    # ... rest unchanged
    cursor_ms += scene_dur_ms
```

→ Subtitle timing match render output.

---

## Test plan

### Test 1: Wire render — verify Plan D path

```bash
# Clear stale renders
cd D:\Projects\story_video_making\test_live
Remove-Item renders\*.mp4 -ErrorAction SilentlyContinue
Remove-Item final.mp4 -ErrorAction SilentlyContinue
Remove-Item final.ass -ErrorAction SilentlyContinue

# In app:
# 1. Reload project
# 2. Click "Render final"
# 3. Verify final.mp4 produced
# 4. Verify final.ass produced (ASS file)
```

Inspect final.mp4:
- Subtitle có karaoke `\kf` (word-by-word fill)
- Position bottom center
- Font Arial 50 bold
- Margin V 100

### Test 2: Review dialog hiển thị đúng

```
1. Click "Process voice" → re-run alignment
2. Dialog mở
3. Verify mỗi scene hiện:
   - Match score color-coded (green ≥ 90, orange 70-89, red < 70)
   - Script vs Voice comparison
   - Render mode dropdown
   - Move HEAD/TAIL buttons
4. Verify silent scenes hiện riêng (no comparison)
```

### Test 3: Move TAIL

```
1. Tạo mismatch: edit voice_mapping.json manual để SCENE-02 voice_out lấn vào SCENE-03
2. Open dialog
3. Verify SCENE-02 score < 90 (orange/red)
4. Click "Move TAIL down" trên SCENE-02
5. Verify:
   - SCENE-02 score tăng
   - SCENE-03 voice_in shrink lại sớm hơn
   - SCENE-03 score tăng
6. Click Save
7. Verify voice_mapping.json updated
```

### Test 4: Render duration override

```
1. Trong dialog, đổi SCENE-03 render mode → "custom" → 8s
2. Save
3. Re-render
4. Verify SCENE-03 trong final.mp4 = 8s (không phải voice 5.98s)
5. Voice play 5.98s + silence 2s cuối
6. Visual play 8s (slow zoom)
```

### Test 5: Re-align all button

```
1. Click "Re-align all"
2. Verify alignment chạy lại
3. Dialog reload với data mới
```

---

## Cleanup checklist

### Files cần XÓA sau khi confirm Plan D work

```
render/composite.py        ← legacy drawtext
render/assemble.py         ← legacy
render/subtitle_filter.py  ← drawtext logic
voice/subtitle_builder.py  ← legacy
```

→ KHÔNG xóa trong Phase 6 này. Đợi sau khi test stable, tag v0.3.0 rồi cleanup riêng.

---

## Build order

1. **Wire render_worker.py** (30 phút) — switch imports + 2-pass logic
2. **Test render Plan D** (15 phút) — verify final.mp4 có ASS karaoke
3. **Build voice/realign_helper.py** (1h) — move HEAD/TAIL functions
4. **Rewrite ui/dialogs/voice_align_review.py** (1.5h) — new layout
5. **Update schema voice_mapping với render_duration** (30 phút)
6. **Update composite_v2 + ass_generator** dùng render_duration (30 phút)
7. **Test E2E** (30 phút)
8. **Commit** "Sprint 3 Phase 6: render wire + manual realign + duration override"

**Total: ~4-5h**

---

## Confirm trước khi code

- [ ] Plan D Phase 1-5 đã build và verify (per VERIFY_REPORT)
- [ ] composite_v2 + assemble_v2 + ass_generator hoạt động (per Phase 5 test)
- [ ] rapidfuzz available (đã install)
- [ ] Test data test_live ready (voice mp3 + scenes.json + sources/)
- [ ] Backup commit hiện tại trước khi build

→ Build sequential, test sau mỗi step. STOP nếu test fail, không skip.
