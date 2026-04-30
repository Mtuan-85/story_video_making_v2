"""Review dialog — voice-first alignment v3 (phase grouping + scale factors).

Layout:
    Phase 1 (start-end, voice_dur)  scale=X.YZ  [warn icon if extreme]
      ├─ SCENE-XX  start [spinbox]  end [spinbox]  dur_adj  scale  conf
      └─ ...
    Phase 2 ...

User can edit voice_in/voice_out per scene; saving marks `method="user_override"`.
Phase metadata is read-only (recompute scale on save if user re-allocates).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.voice_mapping import VoiceMapping


def _scale_color(scale: float) -> str:
    if scale < 0.5 or scale > 1.5:
        return "#c0392b"  # red
    if scale < 0.7 or scale > 1.3:
        return "#e67e22"  # orange
    return "#27ae60"  # green


def _scale_icon(scale: float) -> str:
    if scale < 0.5 or scale > 1.5:
        return "⚠️"
    if scale < 0.7 or scale > 1.3:
        return "⚠"
    return "✓"


class VoiceAlignReviewDialog(QDialog):
    """Review + edit per-scene timestamps with phase grouping view."""

    saved = pyqtSignal(object)  # VoiceMapping

    def __init__(self, voice_mapping: VoiceMapping, parent=None) -> None:
        super().__init__(parent)
        self.mapping = voice_mapping
        self.setWindowTitle("Review Voice Alignment (v3 phases)")
        self.setMinimumSize(1100, 700)
        # (assignment, sp_start, sp_end, dur_item)
        self._row_data: list[tuple[object, QDoubleSpinBox, QDoubleSpinBox, QTableWidgetItem]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        title = QLabel("Voice-first alignment v3 — phases preserve design ratio per group.")
        title.setStyleSheet("color:#666")
        outer.addWidget(title)

        if self.mapping.warnings:
            warn_label = QLabel("\n".join(f"⚠ {w}" for w in self.mapping.warnings))
            warn_label.setStyleSheet("color:#c0392b; font-weight:bold;")
            outer.addWidget(warn_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(12)

        for vf in self.mapping.voice_files:
            file_label = QLabel(f"<b>📁 {vf.file}</b> — duration {vf.duration:.2f}s")
            file_label.setStyleSheet("font-size:13px;")
            body_layout.addWidget(file_label)

            scenes_by_phase: dict[int, list[object]] = {}
            for s in vf.scenes:
                scenes_by_phase.setdefault(s.phase_id, []).append(s)

            if vf.phases:
                for phase in vf.phases:
                    body_layout.addWidget(self._build_phase_block(phase, scenes_by_phase.get(phase.phase_id, [])))
            else:
                # v2-mapping fallback (no phases): single ungrouped block.
                body_layout.addWidget(self._build_phase_block(None, list(vf.scenes)))

        body_layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        if self.mapping.silent_scenes:
            silent_label = QLabel(
                f"Silent scenes (no voice): {', '.join(self.mapping.silent_scenes)}"
            )
            silent_label.setStyleSheet("color:#999; font-style:italic;")
            outer.addWidget(silent_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Save alignment")
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        outer.addLayout(btn_row)

    def _build_phase_block(self, phase, assignments: list) -> QWidget:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        if phase is not None:
            scale = phase.scale_factor
            header = QLabel(
                f"Phase {phase.phase_id} "
                f"({phase.start:.2f}–{phase.end:.2f}s, voice_dur={phase.duration:.2f}s) "
                f" scale=<span style='color:{_scale_color(scale)}'><b>{scale:.2f}</b></span> "
                f"{_scale_icon(scale)}"
            )
            header.setTextFormat(Qt.TextFormat.RichText)
            font = QFont()
            font.setBold(True)
            header.setFont(font)
            layout.addWidget(header)

            if phase.text:
                txt = QLabel(f"  \"{phase.text[:140]}{'…' if len(phase.text) > 140 else ''}\"")
                txt.setStyleSheet("color:#666; font-style:italic;")
                txt.setWordWrap(True)
                layout.addWidget(txt)

        table = QTableWidget(len(assignments), 6)
        table.setHorizontalHeaderLabels(
            ["Scene", "voice_in", "voice_out", "dur_adj", "scale", "conf"]
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        for row_idx, assignment in enumerate(assignments):
            id_item = QTableWidgetItem(assignment.id)
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 0, id_item)

            sp_start = QDoubleSpinBox()
            sp_start.setRange(0, 99999)
            sp_start.setDecimals(2)
            sp_start.setSingleStep(0.1)
            sp_start.setValue(assignment.voice_in)
            table.setCellWidget(row_idx, 1, sp_start)

            sp_end = QDoubleSpinBox()
            sp_end.setRange(0, 99999)
            sp_end.setDecimals(2)
            sp_end.setSingleStep(0.1)
            sp_end.setValue(assignment.voice_out)
            table.setCellWidget(row_idx, 2, sp_end)

            dur_item = QTableWidgetItem(f"{assignment.duration_adjusted:.2f}")
            dur_item.setFlags(dur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 3, dur_item)

            scale_item = QTableWidgetItem(f"{assignment.scale_factor:.2f}")
            scale_item.setFlags(scale_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 4, scale_item)

            conf_item = QTableWidgetItem(f"{assignment.confidence:.2f}")
            conf_item.setFlags(conf_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 5, conf_item)

            sp_start.valueChanged.connect(
                lambda _v, item=dur_item, ss=sp_start, se=sp_end:
                item.setText(f"{se.value() - ss.value():.2f}")
            )
            sp_end.valueChanged.connect(
                lambda _v, item=dur_item, ss=sp_start, se=sp_end:
                item.setText(f"{se.value() - ss.value():.2f}")
            )

            self._row_data.append((assignment, sp_start, sp_end, dur_item))

        table.resizeColumnsToContents()
        table.setMaximumHeight(min(220, 36 + 28 * len(assignments)))
        layout.addWidget(table)
        return block

    def _on_save(self) -> None:
        for assignment, sp_start, sp_end, _ in self._row_data:
            new_start = float(sp_start.value())
            new_end = float(sp_end.value())
            if new_start != assignment.voice_in or new_end != assignment.voice_out:
                assignment.voice_in = new_start
                assignment.voice_out = new_end
                assignment.duration_adjusted = max(0.0, round(new_end - new_start, 2))
                assignment.method = "user_override"
        self.saved.emit(self.mapping)
        self.accept()
