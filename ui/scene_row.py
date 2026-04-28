"""One scene row: status icons, checkbox, preview/edit buttons."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

STATUS_ICON = {
    "pending": "⏳",
    "generating": "🔄",
    "ready": "✓",
    "failed": "❌",
}

VISUAL_TYPE_LABEL = {
    "image_grok": "image_grok",
    "video_grok": "video_grok",
    "slideshow_v4": "slideshow",
    "ken_burns_self": "kb_self",
    "ken_burns_cont": "kb_cont",
}


class SceneRow(QFrame):
    """A single scrollable row representing one scene.

    Signals:
        regen_image_clicked(scene_id)
        preview_image_clicked(scene_id)
        preview_video_clicked(scene_id)
        edit_clicked(scene_id)
        warnings_clicked(scene_id)
        selected_visual_changed(scene_id, "image"|"video"|None)
    """

    regen_image_clicked = pyqtSignal(str)
    preview_image_clicked = pyqtSignal(str)
    preview_video_clicked = pyqtSignal(str)
    edit_clicked = pyqtSignal(str)
    warnings_clicked = pyqtSignal(str)
    selected_visual_changed = pyqtSignal(str, object)
    batch_selection_changed = pyqtSignal(str, bool)

    def __init__(self, scene_id: str, visual_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scene_id = scene_id
        self.visual_type = visual_type

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(40)
        self._build()

    def _build(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(8)

        # Batch select — chọn scene cho batch operations
        self.batch_tick = QCheckBox()
        self.batch_tick.setChecked(True)
        self.batch_tick.setToolTip("Tick = scene này được tính vào batch ảnh/video")
        self.batch_tick.toggled.connect(
            lambda checked: self.batch_selection_changed.emit(self.scene_id, checked)
        )
        row.addWidget(self.batch_tick)

        # Tick — selected_visual (image vs video)
        self.tick = QCheckBox()
        self.tick.setToolTip("Tick = chọn video làm visual; bỏ tick = dùng ảnh")
        self.tick.toggled.connect(self._on_tick_toggled)
        row.addWidget(self.tick)

        # Scene id + overall status
        self.id_label = QLabel(f"<b>{self.scene_id}</b>")
        self.id_label.setMinimumWidth(90)
        row.addWidget(self.id_label)

        self.overall_status = QLabel(STATUS_ICON["pending"])
        self.overall_status.setMinimumWidth(20)
        row.addWidget(self.overall_status)

        # Visual type label
        self.vtype_label = QLabel(VISUAL_TYPE_LABEL.get(self.visual_type, self.visual_type))
        self.vtype_label.setMinimumWidth(80)
        self.vtype_label.setStyleSheet("color:#666")
        row.addWidget(self.vtype_label)

        row.addWidget(self._sep())

        # Per-asset status icons (clickable for preview)
        self.image_btn = self._mk_status_btn("🖼️", "Ảnh: pending")
        self.image_btn.clicked.connect(lambda: self.preview_image_clicked.emit(self.scene_id))
        row.addWidget(self.image_btn)

        self.video_btn = self._mk_status_btn("🎬", "Video: pending")
        self.video_btn.clicked.connect(lambda: self.preview_video_clicked.emit(self.scene_id))
        row.addWidget(self.video_btn)

        self.voice_btn = self._mk_status_btn("🎤", "Voice: pending")
        self.voice_btn.setEnabled(False)  # Sprint 1: voice not built yet
        row.addWidget(self.voice_btn)

        row.addWidget(self._sep())

        # Warning icon
        self.warn_btn = QPushButton("⚠")
        self.warn_btn.setFixedWidth(28)
        self.warn_btn.setEnabled(False)
        self.warn_btn.setToolTip("Không có cảnh báo")
        self.warn_btn.clicked.connect(lambda: self.warnings_clicked.emit(self.scene_id))
        row.addWidget(self.warn_btn)

        # Re-gen
        self.regen_btn = QPushButton("🔄")
        self.regen_btn.setFixedWidth(28)
        self.regen_btn.setToolTip("Re-gen ảnh cho scene này")
        self.regen_btn.clicked.connect(lambda: self.regen_image_clicked.emit(self.scene_id))
        row.addWidget(self.regen_btn)

        # Edit
        self.edit_btn = QPushButton("✏️")
        self.edit_btn.setFixedWidth(28)
        self.edit_btn.setToolTip("Sửa prompt scene này")
        self.edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self.scene_id))
        row.addWidget(self.edit_btn)

        row.addStretch()

    @staticmethod
    def _sep() -> QLabel:
        s = QLabel("|")
        s.setStyleSheet("color:#bbb")
        return s

    @staticmethod
    def _mk_status_btn(icon: str, tip: str) -> QPushButton:
        b = QPushButton(f"{icon} ⏳")
        b.setMinimumWidth(46)
        b.setToolTip(tip)
        b.setEnabled(False)
        return b

    # ------------------------------------------------------------------
    # State application
    # ------------------------------------------------------------------

    def apply_state(self, scene_state: dict[str, Any]) -> None:
        """Update icons + checkbox from a scene-state dict (state.json scene entry)."""
        img = scene_state.get("image", {})
        vid = scene_state.get("video", {})
        voi = scene_state.get("voice", {})
        warnings = scene_state.get("warnings") or []
        selected = scene_state.get("selected_visual")

        self._apply_asset(self.image_btn, "🖼️", img, label="Ảnh")
        self._apply_asset(self.video_btn, "🎬", vid, label="Video")
        self._apply_asset(self.voice_btn, "🎤", voi, label="Voice")

        # Tick = selected_visual; non-emitting update
        self.tick.blockSignals(True)
        self.tick.setChecked(selected == "video")
        self.tick.blockSignals(False)

        # Overall status: worst of image/video. Pending if all pending.
        rank = {"failed": 0, "generating": 1, "pending": 2, "ready": 3}
        statuses = [img.get("status", "pending"), vid.get("status", "pending")]
        worst = min(statuses, key=lambda s: rank.get(s, 2))
        self.overall_status.setText(STATUS_ICON.get(worst, STATUS_ICON["pending"]))

        # Warnings
        if warnings:
            tip = "\n".join(f"[{w.get('code')}] {w.get('msg')}" for w in warnings)
            self.warn_btn.setEnabled(True)
            self.warn_btn.setStyleSheet("color:#e67e22;font-weight:bold")
            self.warn_btn.setToolTip(tip)
        else:
            self.warn_btn.setEnabled(False)
            self.warn_btn.setStyleSheet("")
            self.warn_btn.setToolTip("Không có cảnh báo")

    def _apply_asset(self, btn: QPushButton, icon: str, asset_state: dict, label: str) -> None:
        status = asset_state.get("status", "pending")
        path = asset_state.get("path")
        btn.setText(f"{icon} {STATUS_ICON.get(status, STATUS_ICON['pending'])}")
        btn.setEnabled(status == "ready" and bool(path))
        if status == "ready" and path:
            btn.setToolTip(f"{label}: {path}\n(click để xem preview)")
        elif status == "failed":
            btn.setToolTip(f"{label} fail: {asset_state.get('fail_reason') or '(unknown)'}")
        else:
            btn.setToolTip(f"{label}: {status}")

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _on_tick_toggled(self, checked: bool) -> None:
        self.selected_visual_changed.emit(self.scene_id, "video" if checked else "image")
