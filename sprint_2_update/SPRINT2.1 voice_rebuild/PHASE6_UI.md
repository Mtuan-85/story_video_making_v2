# Phase 6 — UI Cleanup + Auto-Watch Voice Folder

> **Goal**: Bỏ wizard voice_import, add auto-watch folder, simplify Review dialog.
> **Effort**: 2h

---

## Thay đổi UI

### Bỏ

- ❌ `ui/dialogs/voice_import.py` — wizard assign per scene
- ❌ Phase grouping trong Review dialog
- ❌ Spinbox edit voice_in/voice_out manual cho từng scene (vẫn giữ nhưng simplify)

### Thêm

- ✅ Auto-watch folder `voice/` — detect file changes, auto re-trigger
- ✅ Button "Process voice" thay cho "Import voice"
- ✅ Review dialog simplified — chỉ hiển thị scenes table + score per scene
- ✅ Method indicator (deterministic / llm / silent) trong UI
- ✅ Color-code score: green ≥ 75, orange 60-75, red < 60

---

## Module: `core/voice_watcher.py` (NEW)

```python
"""
Watch voice folder for changes, auto-trigger re-alignment.
"""

from pathlib import Path
from PyQt6.QtCore import QFileSystemWatcher, QObject, pyqtSignal, QTimer
from loguru import logger as log


class VoiceFolderWatcher(QObject):
    """
    Watch voice/ folder. Emit signal when contents change.
    Debounce 2s to avoid multiple triggers during file copy.
    """
    
    voice_changed = pyqtSignal()  # emit when ready to re-process
    
    def __init__(self, voice_dir: Path, parent=None):
        super().__init__(parent)
        self.voice_dir = voice_dir
        
        if not voice_dir.exists():
            voice_dir.mkdir(parents=True, exist_ok=True)
        
        self._watcher = QFileSystemWatcher()
        self._watcher.addPath(str(voice_dir))
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        
        # Debounce timer
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._emit_changed)
        self._debounce_ms = 2000
        
        log.info(f"Watching voice folder: {voice_dir}")
    
    def _on_directory_changed(self, path: str):
        log.debug(f"Voice folder changed: {path}")
        # Reset debounce timer
        self._debounce_timer.start(self._debounce_ms)
    
    def _emit_changed(self):
        log.info("Voice folder change confirmed, emitting signal")
        self.voice_changed.emit()
    
    def stop(self):
        if self._watcher:
            self._watcher.removePaths(self._watcher.directories())
        if self._debounce_timer:
            self._debounce_timer.stop()
```

---

## Module: `workers/voice_align_worker.py` (REWRITE)

```python
"""
Voice alignment worker — async wrapper for voice_aligner.
"""

from pathlib import Path
from PyQt6.QtCore import pyqtSignal
from loguru import logger as log

from workers._async_thread import AsyncTaskWorker
from voice.voice_aligner import align_voice_to_scenes


class VoiceAlignWorker(AsyncTaskWorker):
    progress_update = pyqtSignal(str)  # status message
    align_done = pyqtSignal(dict)       # voice_mapping dict
    align_failed = pyqtSignal(str)      # error message
    
    def __init__(
        self,
        scenes: list[dict],
        voice_dir: Path,
        output_dir: Path,
        whisper_model: str = "base",
        language: str = "en",
    ):
        super().__init__()
        self.scenes = scenes
        self.voice_dir = voice_dir
        self.output_dir = output_dir
        self.whisper_model = whisper_model
        self.language = language
    
    async def run(self):
        try:
            self.progress_update.emit("Scanning voice files...")
            
            voice_mapping = await align_voice_to_scenes(
                scenes=self.scenes,
                voice_dir=self.voice_dir,
                output_dir=self.output_dir,
                whisper_model=self.whisper_model,
                language=self.language,
            )
            
            self.align_done.emit(voice_mapping)
        
        except FileNotFoundError as e:
            log.warning(f"Voice folder empty: {e}")
            self.align_failed.emit(f"Không có voice file: {e}")
        
        except Exception as e:
            log.error(f"Voice align failed: {e}")
            self.align_failed.emit(str(e))
```

---

## Module: `ui/dialogs/voice_align_review.py` (REWRITE — simplified)

```python
"""
Simplified Review dialog: scenes table với score per scene.
No phases, no spinbox edit (read-only review).
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView,
)
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtCore import Qt


# Color thresholds
SCORE_HIGH = 75
SCORE_LOW = 60


class VoiceAlignReviewDialog(QDialog):
    """Simple review dialog showing alignment results."""
    
    def __init__(self, voice_mapping: dict, parent=None):
        super().__init__(parent)
        self.voice_mapping = voice_mapping
        
        self.setWindowTitle("Voice Alignment Review")
        self.resize(1000, 600)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Header info
        stats = self.voice_mapping.get("stats", {})
        total = stats.get("total_scenes", 0)
        det = stats.get("deterministic_pass", 0)
        llm = stats.get("llm_fallback_count", 0)
        silent = stats.get("silent", 0)
        no_match = stats.get("no_match", 0)
        
        header = QLabel(
            f"<b>Tổng: {total} scenes</b> | "
            f"Deterministic: {det} | "
            f"LLM fallback: {llm} | "
            f"Silent: {silent} | "
            f"No match: {no_match}"
        )
        layout.addWidget(header)
        
        # Voice files info
        voice_files = self.voice_mapping.get("voice_files", [])
        files_text = "Voice files: " + ", ".join(
            f"{vf['file']} ({vf['duration']:.1f}s)" for vf in voice_files
        )
        layout.addWidget(QLabel(files_text))
        
        # Scenes table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Scene", "voice_in", "voice_out", "dur_orig", "dur_adj", 
            "score", "method"
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        
        scenes = self.voice_mapping.get("scenes", [])
        self.table.setRowCount(len(scenes))
        
        for row, vs in enumerate(scenes):
            self._set_scene_row(row, vs)
        
        layout.addWidget(self.table)
        
        # Buttons
        btn_row = QHBoxLayout()
        
        btn_re_align = QPushButton("🔄 Re-align")
        btn_re_align.setToolTip("Run alignment lại từ đầu")
        btn_re_align.clicked.connect(self._on_re_align)
        btn_row.addWidget(btn_re_align)
        
        btn_row.addStretch()
        
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        
        layout.addLayout(btn_row)
    
    def _set_scene_row(self, row: int, vs: dict):
        # Scene ID
        self.table.setItem(row, 0, QTableWidgetItem(vs["id"]))
        
        # voice_in
        vi = vs.get("voice_in")
        vi_text = f"{vi:.2f}" if vi is not None else "—"
        self.table.setItem(row, 1, QTableWidgetItem(vi_text))
        
        # voice_out
        vo = vs.get("voice_out")
        vo_text = f"{vo:.2f}" if vo is not None else "—"
        self.table.setItem(row, 2, QTableWidgetItem(vo_text))
        
        # duration_original
        d_orig = vs.get("duration_original", 0)
        self.table.setItem(row, 3, QTableWidgetItem(f"{d_orig:.1f}s"))
        
        # duration_adjusted
        d_adj = vs.get("duration_adjusted", 0)
        d_adj_item = QTableWidgetItem(f"{d_adj:.2f}s")
        # Highlight if differ significantly from design
        if d_orig > 0 and abs(d_adj - d_orig) / d_orig > 0.2:
            d_adj_item.setForeground(QBrush(QColor("orange")))
        self.table.setItem(row, 4, d_adj_item)
        
        # Score
        score = vs.get("score")
        if score is None:
            score_text = "—"
            score_color = QColor("gray")
        else:
            score_text = f"{score:.1f}"
            if score >= SCORE_HIGH:
                score_color = QColor("green")
            elif score >= SCORE_LOW:
                score_color = QColor("orange")
            else:
                score_color = QColor("red")
        
        score_item = QTableWidgetItem(score_text)
        score_item.setForeground(QBrush(score_color))
        self.table.setItem(row, 5, score_item)
        
        # Method
        method = vs.get("method", "—")
        method_item = QTableWidgetItem(method)
        if method == "llm":
            method_item.setForeground(QBrush(QColor("blue")))
        elif method == "silent":
            method_item.setForeground(QBrush(QColor("gray")))
        elif method.startswith("no_match") or method.startswith("llm_"):
            method_item.setForeground(QBrush(QColor("red")))
        self.table.setItem(row, 6, method_item)
    
    def _on_re_align(self):
        """Emit signal to parent to re-run alignment."""
        self.done(2)  # custom return code
```

---

## Module: `ui/main_window.py` (UPDATE)

Bỏ wizard voice_import, add auto-watch + button "Process voice":

```python
# Trong _build_ui():

# Bỏ:
# self.btn_import_voice = QPushButton("🎤 Import voice")
# self.btn_import_voice.clicked.connect(self._open_voice_import_wizard)

# Thay bằng:
self.btn_process_voice = QPushButton("🎤 Process voice")
self.btn_process_voice.setToolTip(
    "Run voice alignment với deterministic match + LLM fallback"
)
self.btn_process_voice.clicked.connect(self._on_process_voice)
# Add to toolbar


# Trong _on_load_project():

# Setup voice watcher
from core.voice_watcher import VoiceFolderWatcher

if self._voice_watcher:
    self._voice_watcher.stop()
    self._voice_watcher.deleteLater()

voice_dir = self.project.paths.root / "voice"
self._voice_watcher = VoiceFolderWatcher(voice_dir, parent=self)
self._voice_watcher.voice_changed.connect(self._on_voice_folder_changed)


def _on_voice_folder_changed(self):
    """Auto re-run alignment when voice folder changes."""
    log.info("Voice folder changed, auto re-running alignment")
    self._run_voice_alignment(auto=True)


def _on_process_voice(self):
    """User clicked Process voice button."""
    self._run_voice_alignment(auto=False)


def _run_voice_alignment(self, auto: bool = False):
    """Run voice alignment worker."""
    if not self.project:
        return
    
    # Check voice folder has files
    voice_dir = self.project.paths.root / "voice"
    has_audio = any(voice_dir.glob("*.mp3")) or any(voice_dir.glob("*.wav"))
    
    if not has_audio:
        if not auto:
            QMessageBox.warning(
                self, "Empty",
                "Folder voice/ không có file âm thanh. Bỏ file mp3 vào trước."
            )
        return
    
    # Disable button while running
    self.btn_process_voice.setEnabled(False)
    self.btn_process_voice.setText("🎤 Processing...")
    
    # Get scenes data as dicts
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
    self._voice_worker.progress_update.connect(self._on_voice_progress)
    self._voice_worker.align_done.connect(self._on_voice_align_done)
    self._voice_worker.align_failed.connect(self._on_voice_align_failed)
    self._voice_worker.start()


def _on_voice_progress(self, msg: str):
    log.info(f"Voice align: {msg}")


def _on_voice_align_done(self, voice_mapping: dict):
    self.btn_process_voice.setEnabled(True)
    self.btn_process_voice.setText("🎤 Process voice")
    
    # Refresh project state
    self.project.voice_mapping = voice_mapping  # or reload from disk
    
    # Show review dialog
    from ui.dialogs.voice_align_review import VoiceAlignReviewDialog
    dialog = VoiceAlignReviewDialog(voice_mapping, parent=self)
    result = dialog.exec()
    
    # Handle Re-align button
    if result == 2:
        self._run_voice_alignment(auto=False)


def _on_voice_align_failed(self, reason: str):
    self.btn_process_voice.setEnabled(True)
    self.btn_process_voice.setText("🎤 Process voice")
    
    QMessageBox.critical(self, "Voice align failed", reason)
```

---

## Cleanup checklist

### Files cần XÓA

```
ui/dialogs/voice_import.py     ← bỏ wizard
voice/voice_aligner_v3_old.py  ← nếu có file backup từ rebuild
voice/subtitle_builder.py      ← thay bằng ass_generator
render/subtitle_filter.py      ← drawtext logic, không dùng nữa
```

### Files cần UPDATE

```
core/voice_mapping.py    ← schema v4.0 (bỏ phases)
core/project.py          ← load voice_mapping v4.0
ui/main_window.py        ← bỏ wizard, add auto-watch
workers/voice_align_worker.py  ← rewrite
```

### Backup pattern

Trước khi xóa, copy ra suffix `_legacy_v3`:
```bash
copy voice\voice_aligner.py voice\voice_aligner_legacy_v3.py
```

→ Có thể restore nếu cần. Sau khi rebuild stable, có thể xóa hẳn.

---

## Test plan

### Test 1: Auto-watch trigger

```python
# Open project
# Add voice2.mp3 vào voice/ folder
# Wait 2-3s
# Verify alignment auto-triggers
# Verify voice_mapping.json updated
```

### Test 2: Manual button

```python
# Click "Process voice"
# Verify alignment runs
# Verify Review dialog opens
# Verify table shows scenes với scores + colors
```

### Test 3: Re-align từ Review dialog

```python
# Open Review dialog
# Click "🔄 Re-align"
# Verify alignment re-runs
# Verify dialog re-opens với data mới
```

### Test 4: Empty voice folder

```python
# Empty voice/ folder
# Click "Process voice"
# Verify warning message hiện
# Verify không crash
```

### Test 5: Invalid voice file

```python
# Bỏ file không phải audio (vd .txt) vào voice/
# Click "Process voice"
# Verify lỗi hiện rõ ràng
```

---

## Build order

1. Create `core/voice_watcher.py` (30 phút)
2. Rewrite `workers/voice_align_worker.py` (15 phút)
3. Rewrite `ui/dialogs/voice_align_review.py` (45 phút)
4. Update `ui/main_window.py` (30 phút)
5. Cleanup: delete old files (15 phút)
6. Test all scenarios (30 phút)
7. Commit

**Total: ~2h**

---

## Confirm trước khi code

- [ ] Phase 1-5 đã build xong và stable
- [ ] voice_mapping.json hiện tại đúng schema v4.0
- [ ] Render pipeline work với voice + ASS
- [ ] Backup files cũ trước khi xóa

→ Build xong → tag release v0.3.0.
