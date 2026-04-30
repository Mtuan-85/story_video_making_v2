"""One scene row: thumbnail, dropdowns (visual_type + effect), status icons, edit.

v2 layout:
    [☐] [thumb 60x60] SCENE-XX [▾ visual] [▾ effect] {dur}s [🖼 ✓] [🎬 ✓] [🎤 ✓]  ✏

Bỏ checkbox 2nd, bỏ ⚠ + 🔄 button. Edit button mở Preview Dialog.
Click thumbnail = mở Preview Dialog luôn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

VISUAL_TYPE_OPTIONS = ["image_grok", "video_grok", "slideshow"]
EFFECT_OPTIONS = ["zoom_in", "zoom_out", "no_effect"]
THUMB_SIZE = 60


class SceneRow(QFrame):
    """Single scene row.

    Signals:
        edit_clicked(scene_id)
        preview_image_clicked(scene_id)
        preview_video_clicked(scene_id)
        batch_selection_changed(scene_id, bool)
        visual_type_changed(scene_id, str)
        effect_changed(scene_id, str)
    """

    edit_clicked = pyqtSignal(str)
    preview_image_clicked = pyqtSignal(str)
    preview_video_clicked = pyqtSignal(str)
    batch_selection_changed = pyqtSignal(str, bool)
    visual_type_changed = pyqtSignal(str, str)
    effect_changed = pyqtSignal(str, str)

    def __init__(
        self,
        scene_id: str,
        visual_type: str,
        effect: str = "no_effect",
        duration: int = 0,
        thumbnail_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.scene_id = scene_id
        self._suppress = False

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(72)
        self._build()

        self._initial_visual = visual_type
        self._initial_effect = effect
        self._initial_duration = duration
        self._initial_thumb_path = thumbnail_path
        self._apply_initial_values()

    # --- UI build -------------------------------------------------------------

    def _build(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(8)

        # 1. Single batch checkbox
        self.batch_tick = QCheckBox()
        self.batch_tick.setChecked(True)
        self.batch_tick.setToolTip("Tick = scene này được tính vào batch")
        self.batch_tick.toggled.connect(
            lambda checked: self.batch_selection_changed.emit(self.scene_id, checked)
        )
        row.addWidget(self.batch_tick)

        # 2. Thumbnail (click → open preview)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self.thumb_label.setStyleSheet(
            "border:1px solid #bbb; background:#222; color:#888; font-size:18px;"
        )
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumb_label.setToolTip("Click để mở preview / edit")
        self.thumb_label.mousePressEvent = self._on_thumb_clicked  # type: ignore[assignment]
        row.addWidget(self.thumb_label)

        # 3. Scene id
        self.id_label = QLabel(f"<b>{self.scene_id}</b>")
        self.id_label.setMinimumWidth(90)
        row.addWidget(self.id_label)

        # 4. Visual type dropdown
        self.visual_combo = QComboBox()
        self.visual_combo.addItems(VISUAL_TYPE_OPTIONS)
        self.visual_combo.setMinimumWidth(120)
        self.visual_combo.currentTextChanged.connect(self._on_visual_changed)
        row.addWidget(self.visual_combo)

        # 5. Effect dropdown
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(EFFECT_OPTIONS)
        self.effect_combo.setMinimumWidth(110)
        self.effect_combo.currentTextChanged.connect(self._on_effect_changed)
        row.addWidget(self.effect_combo)

        # 6. Duration label (read-only)
        self.duration_label = QLabel("—")
        self.duration_label.setStyleSheet("color:#666; min-width:36px;")
        row.addWidget(self.duration_label)

        row.addWidget(self._sep())

        # 7. Per-asset status icons (clickable for image/video preview)
        self.image_btn = self._mk_status_btn("🖼", "Ảnh: pending")
        self.image_btn.clicked.connect(lambda: self.preview_image_clicked.emit(self.scene_id))
        row.addWidget(self.image_btn)

        self.video_btn = self._mk_status_btn("🎬", "Video: pending")
        self.video_btn.clicked.connect(lambda: self.preview_video_clicked.emit(self.scene_id))
        row.addWidget(self.video_btn)

        self.voice_btn = self._mk_status_btn("🎤", "Voice: pending")
        self.voice_btn.setEnabled(False)
        row.addWidget(self.voice_btn)

        row.addStretch()

        # 8. Edit button (✏)
        self.edit_btn = QPushButton("✏")
        self.edit_btn.setFixedWidth(28)
        self.edit_btn.setToolTip("Open preview / edit dialog")
        self.edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self.scene_id))
        row.addWidget(self.edit_btn)

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

    # --- Initial values + signal-aware updates --------------------------------

    def _apply_initial_values(self) -> None:
        self._suppress = True
        if self._initial_visual in VISUAL_TYPE_OPTIONS:
            self.visual_combo.setCurrentText(self._initial_visual)
        if self._initial_effect in EFFECT_OPTIONS:
            self.effect_combo.setCurrentText(self._initial_effect)
        self.duration_label.setText(f"{self._initial_duration}s")
        self.set_thumbnail(self._initial_thumb_path)
        self._suppress = False

    def set_thumbnail(self, thumb_path: Path | None) -> None:
        if thumb_path is not None and Path(thumb_path).exists():
            pix = QPixmap(str(thumb_path)).scaled(
                THUMB_SIZE, THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumb_label.setPixmap(pix)
            self.thumb_label.setText("")
        else:
            self.thumb_label.setPixmap(QPixmap())
            self.thumb_label.setText("?")

    def update_visual_type(self, value: str) -> None:
        if value not in VISUAL_TYPE_OPTIONS:
            return
        self._suppress = True
        self.visual_combo.setCurrentText(value)
        self._suppress = False

    def update_effect(self, value: str) -> None:
        if value not in EFFECT_OPTIONS:
            return
        self._suppress = True
        self.effect_combo.setCurrentText(value)
        self._suppress = False

    def update_duration(self, duration: int) -> None:
        self.duration_label.setText(f"{duration}s")

    # --- State application ----------------------------------------------------

    def apply_state(self, scene_state: dict[str, Any]) -> None:
        img = scene_state.get("image", {})
        vid = scene_state.get("video", {})
        voi = scene_state.get("voice", {})

        self._apply_asset(self.image_btn, "🖼", img, label="Ảnh")
        self._apply_asset(self.video_btn, "🎬", vid, label="Video")
        self._apply_asset(self.voice_btn, "🎤", voi, label="Voice")

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

    # --- Internal signal handlers ---------------------------------------------

    def _on_visual_changed(self, value: str) -> None:
        if self._suppress:
            return
        self.visual_type_changed.emit(self.scene_id, value)

    def _on_effect_changed(self, value: str) -> None:
        if self._suppress:
            return
        self.effect_changed.emit(self.scene_id, value)

    def _on_thumb_clicked(self, _event) -> None:
        self.edit_clicked.emit(self.scene_id)

    def is_batch_selected(self) -> bool:
        return self.batch_tick.isChecked()
