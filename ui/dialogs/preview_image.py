"""Preview image dialog — show image at ~screen-fitting size + path footer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class PreviewImageDialog(QDialog):
    """Modal preview for a still image.

    Signals:
        regen_requested(scene_id) — emitted when user clicks "Re-gen ảnh"
    """

    regen_requested = pyqtSignal(str)

    def __init__(self, scene_id: str, image_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.scene_id = scene_id
        self.image_path = Path(image_path)

        self.setWindowTitle(f"Preview ảnh — {scene_id}")
        self.setModal(True)
        self._build_ui()
        self._load_image()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setStyleSheet("background:#1a1a1a; color:#888")
        outer.addWidget(self.image_label, 1)

        path_label = QLabel(str(self.image_path))
        path_label.setStyleSheet("color:#666; font-family:Consolas,monospace; font-size:11px;")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(path_label)

        btn_row = QHBoxLayout()
        btn_open = QPushButton("📂 Mở thư mục")
        btn_open.clicked.connect(self._open_folder)
        btn_row.addWidget(btn_open)

        btn_regen = QPushButton("🔄 Re-gen ảnh")
        btn_regen.clicked.connect(self._on_regen)
        btn_row.addWidget(btn_regen)

        btn_row.addStretch()
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        outer.addLayout(btn_row)

    def _load_image(self) -> None:
        if not self.image_path.exists():
            self.image_label.setText(f"(Không tìm thấy file: {self.image_path})")
            self.resize(600, 400)
            return

        pix = QPixmap(str(self.image_path))
        if pix.isNull():
            self.image_label.setText("(Không đọc được file ảnh)")
            self.resize(600, 400)
            return

        # Cap to ~80% of screen to fit comfortably
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            max_w = int(avail.width() * 0.8)
            max_h = int(avail.height() * 0.8)
            scaled = pix.scaled(
                max_w, max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            scaled = pix

        self.image_label.setPixmap(scaled)
        self.resize(scaled.width() + 40, scaled.height() + 100)

    def _open_folder(self) -> None:
        folder = self.image_path.parent
        if not folder.exists():
            return
        try:
            if os.name == "nt":
                subprocess.run(["explorer", "/select,", str(self.image_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
        except Exception:
            pass

    def _on_regen(self) -> None:
        self.regen_requested.emit(self.scene_id)
        self.accept()
