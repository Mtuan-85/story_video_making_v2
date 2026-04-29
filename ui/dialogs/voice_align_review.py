"""Review dialog — inspect / fix scene timestamps after alignment.

Loads a VoiceMapping, shows one row per scene assignment with editable
voice_in/voice_out spinboxes. Saving mutates the mapping in place and emits
`saved(VoiceMapping)`.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.voice_mapping import VoiceMapping


class VoiceAlignReviewDialog(QDialog):
    """Review + edit per-scene timestamps after alignment."""

    saved = pyqtSignal(object)  # VoiceMapping

    def __init__(self, voice_mapping: VoiceMapping, parent=None) -> None:
        super().__init__(parent)
        self.mapping = voice_mapping
        self.setWindowTitle("Review Voice Alignment")
        self.setMinimumSize(900, 580)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        rows: list[tuple[str, object]] = []
        for vf in self.mapping.voice_files:
            for s in vf.scenes:
                rows.append((vf.file, s))

        self.table = QTableWidget(len(rows), 6)
        self.table.setHorizontalHeaderLabels(
            ["Scene", "Voice file", "Start (s)", "End (s)", "Duration (s)", "Confidence"]
        )
        self._row_data: list[tuple[object, QDoubleSpinBox, QDoubleSpinBox, QTableWidgetItem]] = []

        for row_idx, (filename, assignment) in enumerate(rows):
            self.table.setItem(row_idx, 0, QTableWidgetItem(assignment.id))
            self.table.setItem(row_idx, 1, QTableWidgetItem(filename))

            sp_start = QDoubleSpinBox()
            sp_start.setRange(0, 99999)
            sp_start.setDecimals(2)
            sp_start.setSingleStep(0.1)
            sp_start.setValue(assignment.voice_in)
            self.table.setCellWidget(row_idx, 2, sp_start)

            sp_end = QDoubleSpinBox()
            sp_end.setRange(0, 99999)
            sp_end.setDecimals(2)
            sp_end.setSingleStep(0.1)
            sp_end.setValue(assignment.voice_out)
            self.table.setCellWidget(row_idx, 3, sp_end)

            dur_item = QTableWidgetItem(f"{assignment.voice_out - assignment.voice_in:.2f}")
            self.table.setItem(row_idx, 4, dur_item)
            self.table.setItem(
                row_idx, 5, QTableWidgetItem(f"{assignment.confidence:.2f}")
            )

            sp_start.valueChanged.connect(
                lambda _v, r=row_idx: self._refresh_duration(r)
            )
            sp_end.valueChanged.connect(
                lambda _v, r=row_idx: self._refresh_duration(r)
            )

            self._row_data.append((assignment, sp_start, sp_end, dur_item))

        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)

        if self.mapping.silent_scenes:
            silent_label = QLabel(
                f"Silent scenes: {', '.join(self.mapping.silent_scenes)}"
            )
            silent_label.setStyleSheet("color:#999")
            layout.addWidget(silent_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Save alignment")
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    def _refresh_duration(self, row: int) -> None:
        _assign, sp_start, sp_end, dur_item = self._row_data[row]
        dur_item.setText(f"{sp_end.value() - sp_start.value():.2f}")

    def _on_save(self) -> None:
        for assignment, sp_start, sp_end, _ in self._row_data:
            new_start = float(sp_start.value())
            new_end = float(sp_end.value())
            if new_start != assignment.voice_in or new_end != assignment.voice_out:
                assignment.voice_in = new_start
                assignment.voice_out = new_end
                assignment.method = "user_override"
        self.saved.emit(self.mapping)
        self.accept()
