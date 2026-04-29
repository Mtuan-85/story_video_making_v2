"""Voice import wizard — pick mp3 files, assign scenes, kick off alignment.

Three-step UI in one dialog:
    1. Browse audio files (.mp3 / .wav / .m4a)
    2. Tick which scenes belong to which file (mutually exclusive)
    3. Optionally mark unassigned scenes as silent → emit alignment_requested
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


LANG_CHOICES = [("en", "English"), ("vi", "Tiếng Việt")]
MODEL_CHOICES = ["tiny", "base", "small", "medium"]


class VoiceImportDialog(QDialog):
    """Wizard: browse mp3 → assign scenes → request alignment.

    Emits `alignment_requested(voice_files, assignments, silent_scenes,
    whisper_model, language)` when user clicks Start.
    """

    alignment_requested = pyqtSignal(list, dict, list, str, str)

    def __init__(
        self,
        project_dir: Path,
        scene_ids: list[str],
        default_language: str = "en",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project_dir = Path(project_dir)
        self.scene_ids = list(scene_ids)
        self.voice_files: list[Path] = []
        self.assignments: dict[str, list[str]] = {}
        self._checkboxes: dict[tuple[str, str], QCheckBox] = {}

        self.setWindowTitle("Import Voice Files")
        self.setMinimumSize(720, 540)
        self._build_ui(default_language)

    # UI -----------------------------------------------------------------------

    def _build_ui(self, default_language: str) -> None:
        outer = QVBoxLayout(self)

        # Step 1 — file browser
        step1 = QGroupBox("1. Chọn file voice (.mp3 / .wav / .m4a)")
        s1 = QHBoxLayout(step1)
        self.btn_browse = QPushButton("📁 Browse…")
        self.btn_browse.clicked.connect(self._browse_files)
        self.lbl_files = QLabel("Chưa chọn file")
        self.lbl_files.setStyleSheet("color:#666")
        s1.addWidget(self.btn_browse)
        s1.addWidget(self.lbl_files, 1)
        outer.addWidget(step1)

        # Step 2 — assignment grid
        self.step2 = QGroupBox("2. Gán scenes cho mỗi file (mỗi scene cho 1 file)")
        self.step2_layout = QVBoxLayout(self.step2)
        self.step2_layout.addWidget(QLabel("Browse file ở Step 1 để hiện grid"))
        outer.addWidget(self.step2, 1)

        # Step 3 — options
        step3 = QGroupBox("3. Tùy chọn")
        s3 = QHBoxLayout(step3)
        self.chk_silent = QCheckBox("Đánh dấu scenes không assigned là silent")
        self.chk_silent.setChecked(True)
        s3.addWidget(self.chk_silent)

        s3.addSpacing(20)
        s3.addWidget(QLabel("Whisper model:"))
        self.cb_model = QComboBox()
        self.cb_model.addItems(MODEL_CHOICES)
        self.cb_model.setCurrentText("base")
        s3.addWidget(self.cb_model)

        s3.addSpacing(12)
        s3.addWidget(QLabel("Language:"))
        self.cb_lang = QComboBox()
        for code, label in LANG_CHOICES:
            self.cb_lang.addItem(label, code)
        idx = next(
            (i for i, (c, _) in enumerate(LANG_CHOICES) if c == default_language), 0
        )
        self.cb_lang.setCurrentIndex(idx)
        s3.addWidget(self.cb_lang)
        s3.addStretch()
        outer.addWidget(step3)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_start = QPushButton("Start alignment")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._on_start)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_start)
        outer.addLayout(btn_row)

    # Step 1 -------------------------------------------------------------------

    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn voice files",
            str(self.project_dir / "voice"),
            "Audio (*.mp3 *.wav *.m4a)",
        )
        if not files:
            return
        self.voice_files = [Path(f) for f in files]
        self.lbl_files.setText(f"{len(self.voice_files)} file đã chọn")
        self._build_assignment_grid()

    # Step 2 -------------------------------------------------------------------

    def _clear_step2(self) -> None:
        while self.step2_layout.count():
            item = self.step2_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _build_assignment_grid(self) -> None:
        self._clear_step2()
        self.assignments = {vf.name: [] for vf in self.voice_files}
        self._checkboxes.clear()

        for voice in self.voice_files:
            file_box = QGroupBox(voice.name)
            grid = QGridLayout(file_box)
            for i, sid in enumerate(self.scene_ids):
                cb = QCheckBox(sid)
                cb.toggled.connect(
                    lambda checked, fn=voice.name, s=sid: self._on_assignment_toggled(
                        fn, s, checked
                    )
                )
                self._checkboxes[(voice.name, sid)] = cb
                grid.addWidget(cb, i // 4, i % 4)
            self.step2_layout.addWidget(file_box)
        self.step2_layout.addStretch()
        self._update_start_button()

    def _on_assignment_toggled(self, filename: str, scene_id: str, checked: bool) -> None:
        if checked:
            if scene_id not in self.assignments[filename]:
                self.assignments[filename].append(scene_id)
            # Uncheck same scene in other files (mutual exclusion).
            for fn in self.assignments:
                if fn == filename:
                    continue
                if scene_id in self.assignments[fn]:
                    self.assignments[fn].remove(scene_id)
                cb = self._checkboxes.get((fn, scene_id))
                if cb is not None and cb.isChecked():
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
        else:
            if scene_id in self.assignments[filename]:
                self.assignments[filename].remove(scene_id)

        self._update_start_button()

    def _update_start_button(self) -> None:
        any_assigned = any(scenes for scenes in self.assignments.values())
        self.btn_start.setEnabled(bool(self.voice_files) and any_assigned)

    # Step 3 -------------------------------------------------------------------

    def _on_start(self) -> None:
        all_assigned: set[str] = set()
        for scenes in self.assignments.values():
            all_assigned.update(scenes)
        silent = (
            [s for s in self.scene_ids if s not in all_assigned]
            if self.chk_silent.isChecked()
            else []
        )
        from loguru import logger as log
        log.info(
            f"VoiceImport.start: files={[p.name for p in self.voice_files]} "
            f"assignments={self.assignments} silent={silent}"
        )
        self.alignment_requested.emit(
            list(self.voice_files),
            dict(self.assignments),
            silent,
            self.cb_model.currentText(),
            str(self.cb_lang.currentData()),
        )
        self.accept()
