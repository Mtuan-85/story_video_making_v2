"""One scene row: thumbnail, dropdowns (visual_type + effect), status icons.

v3 layout:
    [☐] [thumb 60x60] SCENE-XX [▾ visual] [▾ effect] {dur}s [🖼 status] [🎬 status] [🛠 status]

Each asset button is state-aware:
  - status=pending/failed: clicking triggers first-gen directly (no dialog)
  - status=ready: clicking opens asset-specific preview/edit dialog
  - status=generating: clicking is ignored (worker still running)

Thumbnail is preview-only (no click action). The ✏ generic edit button
is removed in v3.
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

VISUAL_TYPE_OPTIONS = ["Image", "Video", "slideshow"]
EFFECT_OPTIONS = ["zoom_in", "zoom_out", "no_effect"]
THUMB_SIZE = 60


class NoWheelComboBox(QComboBox):
    # Ignore wheel events so scrolling the scene list never accidentally
    # changes a row's visual_type / effect.
    def wheelEvent(self, e) -> None:  # type: ignore[override]
        e.ignore()


class SceneRow(QFrame):
    """Single scene row.

    Signals:
        image_clicked(scene_id)    — 🖼 clicked
        video_clicked(scene_id)    — 🎬 clicked
        edit_clicked(scene_id)     — 🛠 clicked (slideshow edit)
        batch_selection_changed(scene_id, bool)
        visual_type_changed(scene_id, str)
        effect_changed(scene_id, str)

    main_window routes each signal based on current asset state:
      - pending/failed → direct first-gen (no dialog)
      - ready → open asset-specific dialog
      - generating → ignored
    """

    image_clicked = pyqtSignal(str)
    video_clicked = pyqtSignal(str)
    edit_clicked = pyqtSignal(str)
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

        # 2. Thumbnail (preview only — no click action in v3)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self.thumb_label.setStyleSheet(
            "border:1px solid #bbb; background:#222; color:#888; font-size:18px;"
        )
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setToolTip("Thumbnail (preview only)")
        row.addWidget(self.thumb_label)

        # 3. Scene id
        self.id_label = QLabel(f"<b>{self.scene_id}</b>")
        self.id_label.setMinimumWidth(90)
        row.addWidget(self.id_label)

        # 4. Visual type dropdown
        self.visual_combo = NoWheelComboBox()
        self.visual_combo.addItems(VISUAL_TYPE_OPTIONS)
        self.visual_combo.setMinimumWidth(120)
        self.visual_combo.currentTextChanged.connect(self._on_visual_changed)
        row.addWidget(self.visual_combo)

        # 5. Effect dropdown
        self.effect_combo = NoWheelComboBox()
        self.effect_combo.addItems(EFFECT_OPTIONS)
        self.effect_combo.setMinimumWidth(110)
        self.effect_combo.currentTextChanged.connect(self._on_effect_changed)
        row.addWidget(self.effect_combo)

        # 6. Duration label (read-only)
        self.duration_label = QLabel("—")
        self.duration_label.setStyleSheet("color:#666; min-width:36px;")
        row.addWidget(self.duration_label)

        row.addWidget(self._sep())

        # 7. Per-asset status buttons (state-aware).
        # First click on pending → first-gen (main_window decides).
        # Second+ click on ready → opens asset-specific dialog.
        self.image_btn = self._mk_status_btn(
            "🖼", "Ảnh — click để Gen (lần đầu) hoặc Edit (sau đó)", enabled=True
        )
        self.image_btn.clicked.connect(lambda: self.image_clicked.emit(self.scene_id))
        row.addWidget(self.image_btn)

        self.video_btn = self._mk_status_btn(
            "🎬", "Video — click để Gen (lần đầu) hoặc Edit (sau đó)", enabled=True
        )
        self.video_btn.clicked.connect(lambda: self.video_clicked.emit(self.scene_id))
        row.addWidget(self.video_btn)

        self.edit_asset_btn = self._mk_status_btn(
            "🛠", "Edit slideshow — click để Gen (lần đầu) hoặc Edit zones (sau đó)", enabled=True
        )
        self.edit_asset_btn.clicked.connect(lambda: self.edit_clicked.emit(self.scene_id))
        row.addWidget(self.edit_asset_btn)

        row.addStretch()

    @staticmethod
    def _sep() -> QLabel:
        s = QLabel("|")
        s.setStyleSheet("color:#bbb")
        return s

    @staticmethod
    def _mk_status_btn(icon: str, tip: str, enabled: bool = False) -> QPushButton:
        b = QPushButton(f"{icon} ⏳")
        b.setMinimumWidth(46)
        b.setToolTip(tip)
        b.setEnabled(enabled)
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

    def set_batch_selected(self, checked: bool) -> None:
        self.batch_tick.setChecked(bool(checked))

    # --- State application ----------------------------------------------------

    def apply_state(self, scene_state: dict[str, Any]) -> None:
        img = scene_state.get("image", {})
        vid = scene_state.get("video", {})
        edit = scene_state.get("edit", {})

        self._apply_asset(self.image_btn, "🖼", img, label="Ảnh")
        self._apply_asset(self.video_btn, "🎬", vid, label="Video")
        self._apply_asset(self.edit_asset_btn, "🛠", edit, label="Edit")

    def _apply_asset(self, btn: QPushButton, icon: str, asset_state: dict, label: str) -> None:
        status = asset_state.get("status", "pending")
        path = asset_state.get("path") or asset_state.get("zones_json")
        btn.setText(f"{icon} {STATUS_ICON.get(status, STATUS_ICON['pending'])}")
        # Disable button only while a worker is actively running for THIS asset.
        # Otherwise enabled — first click = gen, subsequent click = edit.
        btn.setEnabled(status != "generating")
        if status == "ready" and path:
            btn.setToolTip(f"{label}: {path}\n(click để mở edit/preview)")
        elif status == "failed":
            btn.setToolTip(f"{label} fail: {asset_state.get('fail_reason') or '(unknown)'}\n(click để Gen lại)")
        elif status == "generating":
            btn.setToolTip(f"{label}: đang chạy...")
        else:
            btn.setToolTip(f"{label}: chưa có\n(click để Gen lần đầu)")

    # --- Internal signal handlers ---------------------------------------------

    def _on_visual_changed(self, value: str) -> None:
        if self._suppress:
            return
        self.visual_type_changed.emit(self.scene_id, value)

    def _on_effect_changed(self, value: str) -> None:
        if self._suppress:
            return
        self.effect_changed.emit(self.scene_id, value)

    def is_batch_selected(self) -> bool:
        return self.batch_tick.isChecked()
