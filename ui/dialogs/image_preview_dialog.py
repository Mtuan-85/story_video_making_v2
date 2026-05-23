"""ImagePreviewDialog — focused on Image asset only.

Triggered when user clicks 🖼 button on a scene that has image.status='ready'.
For 'pending' state, main_window triggers Gen Image directly (no dialog).

Layout:
    [Image display]
    Script: [textarea]
    Image Prompt: [textarea]
    [💾 Save] [🖼 Gen Image] [⚡ Fast] [📁 Folder] [Đóng]
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ImagePreviewDialog(QDialog):
    """Preview + edit dialog focused on Image asset."""

    save_requested = pyqtSignal(str, dict)        # (scene_id, updates)
    gen_image_requested = pyqtSignal(str, bool)    # (scene_id, fast_mode)

    def __init__(
        self,
        scene,
        scene_state: dict,
        project_root: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.scene = scene
        self.scene_state = scene_state or {}
        self.project_root = Path(project_root)

        self.setWindowTitle(f"Image — {scene.id}")
        self.resize(820, 720)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 1. Image display
        self.visual_frame = QFrame()
        self.visual_frame.setMinimumHeight(380)
        self.visual_frame.setStyleSheet("background:#000;")
        outer.addWidget(self.visual_frame, 1)
        self._load_image()

        # 2. Script
        outer.addWidget(QLabel("<b>Script:</b>"))
        self.story_edit = QTextEdit()
        self.story_edit.setPlainText(self.scene.script or "")
        self.story_edit.setMaximumHeight(80)
        outer.addWidget(self.story_edit)

        # 3. Image prompt
        outer.addWidget(QLabel("<b>Image Prompt:</b>"))
        self.image_prompt_edit = QTextEdit()
        self.image_prompt_edit.setPlainText(self.scene.imagePrompt or "")
        self.image_prompt_edit.setMaximumHeight(160)
        outer.addWidget(self.image_prompt_edit)

        # 4. Buttons
        btns = QHBoxLayout()

        b_save = QPushButton("💾 Save")
        b_save.clicked.connect(self._on_save)
        btns.addWidget(b_save)

        b_gen = QPushButton("🖼 Gen Image")
        b_gen.setToolTip("Save + regenerate image (overwrite existing)")
        b_gen.clicked.connect(self._on_gen_image)
        btns.addWidget(b_gen)

        self.fast_check = QCheckBox("⚡ Fast")
        self.fast_check.setToolTip(
            "Fast mode: paste prompt + wait 5s instead of typing each char.\n"
            "Áp dụng cho lần Gen này, không persist."
        )
        btns.addWidget(self.fast_check)

        b_folder = QPushButton("📁 Folder")
        b_folder.clicked.connect(self._open_folder)
        btns.addWidget(b_folder)

        btns.addStretch()

        b_close = QPushButton("Đóng")
        b_close.clicked.connect(self.reject)
        btns.addWidget(b_close)

        outer.addLayout(btns)

    def _load_image(self) -> None:
        layout = QVBoxLayout(self.visual_frame)
        layout.setContentsMargins(0, 0, 0, 0)

        img_state = self.scene_state.get("image", {})
        path = img_state.get("path")
        if path is None or img_state.get("status") != "ready":
            label = QLabel("(Chưa có image — bấm Gen Image)")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color:#999;")
            layout.addWidget(label)
            return

        full = self._abs(path)
        if not full.exists():
            label = QLabel(f"(File không tồn tại: {path})")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color:#999;")
            layout.addWidget(label)
            return

        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(str(full)).scaled(
            780,
            440,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(pix)
        layout.addWidget(label)

    def _abs(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        return p if p.is_absolute() else self.project_root / p

    def _collect_updates(self) -> dict:
        return {
            "script": self.story_edit.toPlainText().strip() or None,
            "imagePrompt": self.image_prompt_edit.toPlainText().strip(),
        }

    def _on_save(self) -> None:
        self.save_requested.emit(self.scene.id, self._collect_updates())
        self.accept()

    def _on_gen_image(self) -> None:
        self.save_requested.emit(self.scene.id, self._collect_updates())
        self.gen_image_requested.emit(self.scene.id, self.fast_check.isChecked())
        self.accept()

    def _open_folder(self) -> None:
        img_state = self.scene_state.get("image", {})
        path = img_state.get("path")
        if path:
            full = self._abs(path)
            try:
                os.startfile(str(full.parent))
            except Exception:
                pass
        else:
            try:
                os.startfile(str(self.project_root / "sources"))
            except Exception:
                pass
