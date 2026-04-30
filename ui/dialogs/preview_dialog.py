"""Unified preview + edit dialog for one scene.

Triggered by clicking a row's thumbnail OR the ✏ edit button.
Shows the current visual (image static; video via VLC if available, else
external player), editable story / prompts / visual_type / effect / duration,
and Save / Re-gen / Open folder buttons.

Save: emit `save_requested(scene_id, updates)` — main_window persists via
`Project.update_scene_fields`.

Re-gen: emit save first (sync state), then `regen_requested(scene_id)`.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

VISUAL_TYPES = ["image_grok", "video_grok", "slideshow"]
EFFECTS = ["zoom_in", "zoom_out", "no_effect"]


class PreviewDialog(QDialog):
    """Unified scene preview + edit."""

    save_requested = pyqtSignal(str, dict)  # scene_id, updates
    regen_requested = pyqtSignal(str)  # scene_id

    def __init__(self, scene, scene_state: dict, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scene = scene
        self.scene_state = scene_state or {}
        self.project_root = Path(project_root)
        self._vlc = None
        self._vlc_player = None

        self.setWindowTitle(f"Preview — {scene.id}")
        self.resize(960, 760)
        self._build_ui()

    # --- UI ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 1. Visual preview
        self.visual_frame = QFrame()
        self.visual_frame.setMinimumHeight(400)
        self.visual_frame.setStyleSheet("background:#000;")
        outer.addWidget(self.visual_frame, 1)
        self._load_visual()

        # 2. Story
        outer.addWidget(QLabel("<b>Story (English):</b>"))
        self.story_edit = QTextEdit()
        self.story_edit.setPlainText(self.scene.story_en or "")
        self.story_edit.setMaximumHeight(70)
        outer.addWidget(self.story_edit)

        # 3. Image prompt
        outer.addWidget(QLabel("<b>Image Prompt:</b>"))
        self.image_prompt_edit = QTextEdit()
        self.image_prompt_edit.setPlainText(self.scene.imagePrompt or "")
        self.image_prompt_edit.setMaximumHeight(110)
        outer.addWidget(self.image_prompt_edit)

        # 4. Video prompt (optional)
        outer.addWidget(QLabel("<b>Video Prompt (optional):</b>"))
        self.video_prompt_edit = QTextEdit()
        self.video_prompt_edit.setPlainText(self.scene.videoPrompt or "")
        self.video_prompt_edit.setMaximumHeight(70)
        outer.addWidget(self.video_prompt_edit)

        # 5. Meta row
        meta = QHBoxLayout()
        meta.addWidget(QLabel("Visual:"))
        self.visual_combo = QComboBox()
        self.visual_combo.addItems(VISUAL_TYPES)
        self.visual_combo.setCurrentText(self.scene.visual_type)
        meta.addWidget(self.visual_combo)
        meta.addSpacing(12)

        meta.addWidget(QLabel("Effect:"))
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(EFFECTS)
        self.effect_combo.setCurrentText(self.scene.effect or "no_effect")
        meta.addWidget(self.effect_combo)
        meta.addSpacing(12)

        meta.addWidget(QLabel("Duration:"))
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 60)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setValue(int(self.scene.duration))
        meta.addWidget(self.duration_spin)

        meta.addStretch()
        outer.addLayout(meta)

        # 6. Buttons
        btns = QHBoxLayout()
        b_save = QPushButton("💾 Save")
        b_save.clicked.connect(self._on_save)
        btns.addWidget(b_save)

        b_regen = QPushButton("🔄 Save & Re-gen")
        b_regen.clicked.connect(self._on_regen)
        btns.addWidget(b_regen)

        b_open = QPushButton("📁 Folder")
        b_open.clicked.connect(self._open_folder)
        btns.addWidget(b_open)

        btns.addStretch()
        b_close = QPushButton("Đóng")
        b_close.clicked.connect(self.reject)
        btns.addWidget(b_close)
        outer.addLayout(btns)

    # --- Visual --------------------------------------------------------------

    def _resolve_visual(self) -> tuple[Path | None, str]:
        """Return (path, kind) where kind ∈ {'image','video','none'}.

        Prefer video if scene has a ready video; otherwise image.
        """
        vid_state = self.scene_state.get("video", {})
        if vid_state.get("status") == "ready" and vid_state.get("path"):
            return self._abs(vid_state["path"]), "video"
        img_state = self.scene_state.get("image", {})
        if img_state.get("status") == "ready" and img_state.get("path"):
            return self._abs(img_state["path"]), "image"
        return None, "none"

    def _abs(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        return p if p.is_absolute() else self.project_root / p

    def _load_visual(self) -> None:
        layout = QVBoxLayout(self.visual_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        path, kind = self._resolve_visual()
        if path is None or not path.exists():
            label = QLabel("(Chưa có visual — bấm Re-gen sau khi lưu prompt)")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color:#999;")
            layout.addWidget(label)
            return
        if kind == "image":
            self._load_image(layout, path)
        else:
            self._load_video(layout, path)

    def _load_image(self, layout: QVBoxLayout, path: Path) -> None:
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(str(path)).scaled(
            900, 480,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(pix)
        layout.addWidget(label)

    def _load_video(self, layout: QVBoxLayout, path: Path) -> None:
        try:
            import vlc  # type: ignore
        except Exception:
            label = QLabel(f"VLC chưa cài — bấm để mở {path.name} bằng player hệ thống")
            label.setStyleSheet("color:#e67e22;")
            layout.addWidget(label)
            btn = QPushButton(f"▶ Mở {path.name}")
            btn.clicked.connect(lambda: os.startfile(str(path)))
            layout.addWidget(btn)
            return

        self._vlc = vlc.Instance("--no-xlib")  # type: ignore[attr-defined]
        self._vlc_player = self._vlc.media_player_new()
        media = self._vlc.media_new(str(path))
        self._vlc_player.set_media(media)

        video_widget = QFrame()
        video_widget.setMinimumHeight(380)
        video_widget.setStyleSheet("background:#000;")
        layout.addWidget(video_widget, 1)

        # Bind player to widget HWND (Windows) / xid (Linux).
        if hasattr(video_widget, "winId"):
            try:
                self._vlc_player.set_hwnd(int(video_widget.winId()))
            except Exception:
                pass

        controls = QHBoxLayout()
        b_play = QPushButton("▶ Play")
        b_play.clicked.connect(lambda: self._vlc_player.play())
        controls.addWidget(b_play)
        b_pause = QPushButton("⏸ Pause")
        b_pause.clicked.connect(lambda: self._vlc_player.pause())
        controls.addWidget(b_pause)
        b_stop = QPushButton("⏹ Stop")
        b_stop.clicked.connect(lambda: self._vlc_player.stop())
        controls.addWidget(b_stop)
        controls.addStretch()
        layout.addLayout(controls)

    # --- Save / Re-gen / Folder ---------------------------------------------

    def _collect_updates(self) -> dict:
        return {
            "story_en": self.story_edit.toPlainText().strip() or None,
            "imagePrompt": self.image_prompt_edit.toPlainText().strip(),
            "videoPrompt": (self.video_prompt_edit.toPlainText().strip() or None),
            "visual_type": self.visual_combo.currentText(),
            "effect": self.effect_combo.currentText(),
            "duration": int(self.duration_spin.value()),
        }

    def _on_save(self) -> None:
        self.save_requested.emit(self.scene.id, self._collect_updates())
        self.accept()

    def _on_regen(self) -> None:
        self.save_requested.emit(self.scene.id, self._collect_updates())
        self.regen_requested.emit(self.scene.id)
        self.accept()

    def _open_folder(self) -> None:
        path, _ = self._resolve_visual()
        if path is not None:
            try:
                os.startfile(str(path.parent))
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        if self._vlc_player is not None:
            try:
                self._vlc_player.stop()
            except Exception:
                pass
        super().closeEvent(event)
