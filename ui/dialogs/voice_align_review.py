"""Review dialog for voice_mapping v4.0 (Plan D) — compact 2-column layout.

Per scene card:
    Header   : SCENE id  +  Match score (color-coded)
    Left col : Script (designed) text  /  Voice (transcribed cut) text
    Right col: Render duration (mode + custom spin)  /  Voice timing
    Bottom   : Move HEAD / Move TAIL buttons

Top toolbar: Re-align all (rerun Plan D)  Save  Cancel
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger as log
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.voice_mapping import VoiceMapping

SCORE_GREEN = "#27ae60"
SCORE_ORANGE = "#e67e22"
SCORE_RED = "#c0392b"
SCORE_GREY = "#888888"


def _score_color(score: float | None) -> str:
    if score is None:
        return SCORE_GREY
    if score >= 90:
        return SCORE_GREEN
    if score >= 70:
        return SCORE_ORANGE
    return SCORE_RED


class _SceneRow(QFrame):
    """Compact 2-column scene editor card."""

    move_head_clicked = pyqtSignal(str)
    move_tail_clicked = pyqtSignal(str)

    def __init__(
        self,
        assignment: dict[str, Any],
        scene_data: dict[str, Any] | None,
        is_first: bool,
        is_last: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.scene_id: str = assignment["id"]
        self.assignment = assignment
        self.scene_data = scene_data or {}
        self.is_first = is_first
        self.is_last = is_last

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { border:1px solid #ccc; border-radius:4px; "
            "padding:6px; }"
            " QTextEdit { background:#fafafa; border:1px solid #ddd; }"
        )
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(6)

        # === Top: Scene ID + Match score ===
        top = QHBoxLayout()
        title = QLabel(f"<b style='font-size:11pt'>{self.scene_id}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(title)
        top.addStretch()

        method = self.assignment.get("method") or (
            "silent" if self.assignment.get("is_silent") else "—"
        )
        score = self.assignment.get("score")
        if self.assignment.get("is_silent"):
            score_text = f"SILENT ({method})"
            color = SCORE_GREY
        elif score is None:
            score_text = f"— ({method})"
            color = SCORE_GREY
        else:
            score_text = f"Match: {score:.1f}% ({method})"
            color = _score_color(score)
        self.score_label = QLabel(score_text)
        self.score_label.setStyleSheet(
            f"color:{color}; font-weight:bold; padding:2px 6px;"
        )
        top.addWidget(self.score_label)
        outer.addLayout(top)

        # Silent: skip the dual-column body, render a small note instead.
        if self.assignment.get("is_silent"):
            note = QLabel("<i>Silent scene — keeps design duration</i>")
            note.setStyleSheet("color:#888; padding:6px;")
            outer.addWidget(note)
            return

        # === Body: 2-column grid ===
        grid = QGridLayout()
        grid.setColumnStretch(0, 3)  # left column wider (text)
        grid.setColumnStretch(1, 2)  # right column narrower (controls)
        grid.setSpacing(8)

        # Row 0 — labels
        grid.addWidget(self._heading("📜 <b>Script</b>"), 0, 0)
        grid.addWidget(self._heading("Render duration", align_right=True), 0, 1)

        # Row 1 — Script text + render mode controls
        script_text = self.scene_data.get("script") or ""
        self.script_view = QTextEdit()
        self.script_view.setPlainText(script_text)
        self.script_view.setReadOnly(True)
        self.script_view.setMaximumHeight(70)
        self.script_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        grid.addWidget(self.script_view, 1, 0)
        grid.addWidget(self._build_render_panel(), 1, 1)

        # Row 2 — labels
        grid.addWidget(self._heading("🎤 <b>Voice</b>"), 2, 0)
        grid.addWidget(self._heading("Voice timing", align_right=True), 2, 1)

        # Row 3 — Voice text + timing readout
        self.voice_view = QTextEdit()
        self.voice_view.setPlainText(self.assignment.get("matched_text") or "")
        self.voice_view.setReadOnly(True)
        self.voice_view.setMaximumHeight(70)
        self.voice_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        grid.addWidget(self.voice_view, 3, 0)
        grid.addWidget(self._build_timing_panel(), 3, 1)

        outer.addLayout(grid)

        # === Bottom: Move buttons ===
        btn_row = QHBoxLayout()
        self.btn_head = QPushButton("◀ Move HEAD up to previous")
        self.btn_head.setEnabled(not self.is_first)
        self.btn_head.clicked.connect(
            lambda: self.move_head_clicked.emit(self.scene_id)
        )
        btn_row.addWidget(self.btn_head)
        btn_row.addStretch()
        self.btn_tail = QPushButton("Move TAIL down to next ▶")
        self.btn_tail.setEnabled(not self.is_last)
        self.btn_tail.clicked.connect(
            lambda: self.move_tail_clicked.emit(self.scene_id)
        )
        btn_row.addWidget(self.btn_tail)
        outer.addLayout(btn_row)

    @staticmethod
    def _heading(text: str, *, align_right: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        if align_right:
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        return lbl

    def _build_render_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        mode_row = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["voice", "design", "custom"])
        current_mode = self.assignment.get("render_mode") or "voice"
        idx = self.mode_combo.findText(current_mode)
        self.mode_combo.setCurrentIndex(max(0, idx))
        mode_row.addWidget(self.mode_combo)

        self.custom_spin = QDoubleSpinBox()
        self.custom_spin.setRange(0.5, 120.0)
        self.custom_spin.setSuffix(" s")
        self.custom_spin.setSingleStep(0.5)
        self.custom_spin.setValue(
            float(
                self.assignment.get("custom_duration")
                or self.assignment.get("duration_original", 5)
            )
        )
        self.custom_spin.setEnabled(current_mode == "custom")
        self.mode_combo.currentTextChanged.connect(
            lambda mode: self.custom_spin.setEnabled(mode == "custom")
        )
        mode_row.addWidget(self.custom_spin)
        layout.addLayout(mode_row)

        design = float(self.assignment.get("duration_original", 0) or 0)
        info = QLabel(f"Design: {design:.2f}s")
        info.setStyleSheet("color:#666; font-size:9pt;")
        layout.addWidget(info)
        layout.addStretch()
        return panel

    def _build_timing_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        v_in = float(self.assignment.get("voice_in") or 0)
        v_out = float(self.assignment.get("voice_out") or 0)
        dur = max(0.0, v_out - v_in)

        self.timing_label = QLabel(f"⏱ {v_in:.2f} → {v_out:.2f}s")
        self.timing_label.setStyleSheet(
            "font-family:Consolas,monospace; font-size:9pt;"
        )
        layout.addWidget(self.timing_label)

        self.dur_label = QLabel(f"Duration: <b>{dur:.2f}s</b>")
        self.dur_label.setTextFormat(Qt.TextFormat.RichText)
        self.dur_label.setStyleSheet("font-size:9pt;")
        layout.addWidget(self.dur_label)
        layout.addStretch()
        return panel

    # ------------------------------------------------------------- refresh

    def refresh_after_realign(self, assignment: dict[str, Any]) -> None:
        self.assignment = assignment
        if self.assignment.get("is_silent"):
            return

        score = assignment.get("score")
        method = assignment.get("method") or "—"
        color = _score_color(score)
        if score is None:
            txt = f"— ({method})"
        else:
            txt = f"Match: {score:.1f}% ({method})"
        self.score_label.setText(txt)
        self.score_label.setStyleSheet(
            f"color:{color}; font-weight:bold; padding:2px 6px;"
        )

        self.voice_view.setPlainText(assignment.get("matched_text") or "")

        v_in = float(assignment.get("voice_in") or 0)
        v_out = float(assignment.get("voice_out") or 0)
        dur = max(0.0, v_out - v_in)
        self.timing_label.setText(f"⏱ {v_in:.2f} → {v_out:.2f}s")
        self.dur_label.setText(f"Duration: <b>{dur:.2f}s</b>")

    def collect_render_settings(self) -> None:
        if self.assignment.get("is_silent"):
            self.assignment["render_mode"] = "voice"
            self.assignment["custom_duration"] = None
            self.assignment["render_duration"] = self.assignment.get(
                "duration_original", 5
            )
            return

        mode = self.mode_combo.currentText()
        self.assignment["render_mode"] = mode
        if mode == "custom":
            self.assignment["custom_duration"] = round(self.custom_spin.value(), 2)
        else:
            self.assignment["custom_duration"] = None

        v_in = float(self.assignment.get("voice_in") or 0)
        v_out = float(self.assignment.get("voice_out") or 0)
        voice_dur = max(0.0, v_out - v_in)
        if mode == "voice":
            self.assignment["render_duration"] = round(voice_dur, 2)
        elif mode == "design":
            self.assignment["render_duration"] = self.assignment.get(
                "duration_original", 5
            )
        else:
            self.assignment["render_duration"] = round(self.custom_spin.value(), 2)


class VoiceAlignReviewDialog(QDialog):
    """Voice alignment review (v4.0 — Plan D)."""

    save_requested = pyqtSignal(object)  # emits VoiceMapping after Save
    re_align_requested = pyqtSignal()

    def __init__(
        self,
        voice_mapping: VoiceMapping,
        scenes_data: list[dict[str, Any]] | None = None,
        whisper_words: list[dict[str, Any]] | None = None,
        whisper_words_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mapping = voice_mapping
        self.scenes_data = scenes_data or []
        self._whisper_words = whisper_words
        self._whisper_words_path = whisper_words_path

        self.setWindowTitle("Voice Alignment Review")
        self.resize(1100, 720)

        self._scene_data_by_id = {s["id"]: s for s in self.scenes_data}
        self._mapping_dict: dict[str, Any] = self.mapping.model_dump(mode="json")
        self._rows: dict[str, _SceneRow] = {}
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)

        stats = self.mapping.stats
        header = QLabel(
            f"<b>Plan D alignment</b> — "
            f"scenes: {stats.total_scenes}  |  "
            f"deterministic: {stats.deterministic_pass}  |  "
            f"LLM fallback: {stats.llm_fallback_count}  |  "
            f"silent: {stats.silent}  |  "
            f"voice files: {len(self.mapping.voice_files)}"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setSpacing(6)
        self._populate_rows()
        scroll.setWidget(self._body)
        outer.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_realign = QPushButton("Re-align all (rerun Plan D)")
        btn_realign.clicked.connect(self._on_re_align)
        btn_row.addWidget(btn_realign)
        btn_row.addStretch()
        btn_save = QPushButton("Save")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        outer.addLayout(btn_row)

    def _populate_rows(self) -> None:
        scenes = self._mapping_dict.get("scenes", [])
        for idx, vs in enumerate(scenes):
            row = _SceneRow(
                assignment=vs,
                scene_data=self._scene_data_by_id.get(vs["id"]),
                is_first=(idx == 0),
                is_last=(idx == len(scenes) - 1),
            )
            row.move_head_clicked.connect(self._on_move_head)
            row.move_tail_clicked.connect(self._on_move_tail)
            self._body_layout.addWidget(row)
            self._rows[vs["id"]] = row
        self._body_layout.addStretch()

    # ------------------------------------------------------------- ops

    def _ensure_whisper_words(self) -> list[dict[str, Any]]:
        if self._whisper_words is not None:
            return self._whisper_words
        if self._whisper_words_path and self._whisper_words_path.exists():
            try:
                self._whisper_words = json.loads(
                    self._whisper_words_path.read_text(encoding="utf-8")
                )
                return self._whisper_words
            except Exception as e:
                log.error(f"Failed to load whisper_words.json: {e}")
        raise FileNotFoundError(
            "whisper_words.json missing — re-run alignment to enable manual moves."
        )

    def _on_move_head(self, scene_id: str) -> None:
        try:
            words = self._ensure_whisper_words()
            from voice.realign_helper import move_head_to_previous

            move_head_to_previous(
                self._mapping_dict, scene_id, words, self.scenes_data
            )
        except Exception as e:
            QMessageBox.warning(self, "Move HEAD failed", str(e))
            return
        self._refresh_affected(scene_id, neighbor_offset=-1)

    def _on_move_tail(self, scene_id: str) -> None:
        try:
            words = self._ensure_whisper_words()
            from voice.realign_helper import move_tail_to_next

            move_tail_to_next(
                self._mapping_dict, scene_id, words, self.scenes_data
            )
        except Exception as e:
            QMessageBox.warning(self, "Move TAIL failed", str(e))
            return
        self._refresh_affected(scene_id, neighbor_offset=+1)

    def _refresh_affected(self, scene_id: str, neighbor_offset: int) -> None:
        ids = [s["id"] for s in self._mapping_dict.get("scenes", [])]
        cur_idx = ids.index(scene_id)
        nbr_idx = cur_idx + neighbor_offset
        for idx in (cur_idx, nbr_idx):
            if 0 <= idx < len(ids):
                sid = ids[idx]
                if sid in self._rows:
                    self._rows[sid].refresh_after_realign(
                        self._mapping_dict["scenes"][idx]
                    )

    def _on_re_align(self) -> None:
        self.re_align_requested.emit()
        self.done(2)

    def _on_save(self) -> None:
        for vs in self._mapping_dict["scenes"]:
            row = self._rows.get(vs["id"])
            if row:
                row.collect_render_settings()
        try:
            self.mapping = VoiceMapping.model_validate(self._mapping_dict)
        except Exception as e:
            QMessageBox.critical(self, "Schema validation failed", str(e))
            return
        self.save_requested.emit(self.mapping)
        self.accept()
