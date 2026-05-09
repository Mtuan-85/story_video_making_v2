"""Unified preview + edit dialog for one scene.

Triggered by clicking a row's thumbnail, the 🖼/🎬 status buttons, or the ✏
edit button. Shows the current visual (image static; video via Qt's native
QMediaPlayer + QVideoWidget — no external player required), editable
story / prompts / visual_type / effect / duration, and three action buttons:

  💾 Save        — persist edits without gen.
  🖼 Gen Image   — persist edits, then run image worker (overwrites existing).
  🎞 Gen Video   — persist edits, then run video worker. Dispatches by
                   visual_type: video_grok (I2V) or slideshow.

Signals:
    save_requested(scene_id, updates)        — main_window persists via
                                                Project.update_scene_fields.
    gen_image_requested(scene_id)            — main_window dispatches image gen.
    gen_animation_requested(scene_id)        — main_window dispatches video gen.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

VISUAL_TYPES = ["image_grok", "video_grok", "slideshow"]
EFFECTS = ["zoom_in", "zoom_out", "no_effect"]


class NoWheelComboBox(QComboBox):
    # Ignore wheel events so scrolling the dialog never accidentally
    # cycles the visual_type / effect selection.
    def wheelEvent(self, e) -> None:  # type: ignore[override]
        e.ignore()


class PreviewDialog(QDialog):
    """Unified scene preview + edit."""

    save_requested = pyqtSignal(str, dict)  # scene_id, updates
    gen_image_requested = pyqtSignal(str)  # scene_id
    gen_animation_requested = pyqtSignal(str)  # scene_id

    def __init__(self, scene, scene_state: dict, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scene = scene
        self.scene_state = scene_state or {}
        self.project_root = Path(project_root)
        self._media_player: QMediaPlayer | None = None
        self._audio_output: QAudioOutput | None = None
        self._position_slider: QSlider | None = None
        self._slider_dragging = False

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
        self.visual_combo = NoWheelComboBox()
        self.visual_combo.addItems(VISUAL_TYPES)
        self.visual_combo.setCurrentText(self.scene.visual_type)
        meta.addWidget(self.visual_combo)
        meta.addSpacing(12)

        meta.addWidget(QLabel("Effect:"))
        self.effect_combo = NoWheelComboBox()
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

        b_gen_image = QPushButton("🖼 Gen Image")
        b_gen_image.setToolTip("Save prompt + Generate image (overwrite existing)")
        b_gen_image.clicked.connect(self._on_gen_image)
        btns.addWidget(b_gen_image)

        b_gen_anim = QPushButton("🎞 Gen Video")
        b_gen_anim.setToolTip("Save prompt + Generate video (requires existing image for I2V)")
        b_gen_anim.clicked.connect(self._on_gen_animation)
        btns.addWidget(b_gen_anim)

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
        video_widget = QVideoWidget()
        video_widget.setMinimumHeight(380)
        video_widget.setStyleSheet("background:#000;")
        layout.addWidget(video_widget, 1)

        self._media_player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.setVideoOutput(video_widget)
        self._media_player.setSource(QUrl.fromLocalFile(str(path)))

        controls = QHBoxLayout()
        b_play = QPushButton("▶ Play")
        b_play.clicked.connect(self._media_player.play)
        controls.addWidget(b_play)
        b_pause = QPushButton("⏸ Pause")
        b_pause.clicked.connect(self._media_player.pause)
        controls.addWidget(b_pause)
        b_stop = QPushButton("⏹ Stop")
        b_stop.clicked.connect(self._media_player.stop)
        controls.addWidget(b_stop)

        self._position_slider = QSlider(Qt.Orientation.Horizontal)
        self._position_slider.setRange(0, 0)
        self._position_slider.sliderPressed.connect(self._on_slider_pressed)
        self._position_slider.sliderReleased.connect(self._on_slider_released)
        controls.addWidget(self._position_slider, 1)

        self._media_player.positionChanged.connect(self._on_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        self._media_player.errorOccurred.connect(self._on_media_error)
        layout.addLayout(controls)

    def _on_position_changed(self, pos: int) -> None:
        if self._position_slider is not None and not self._slider_dragging:
            self._position_slider.setValue(pos)

    def _on_duration_changed(self, dur: int) -> None:
        if self._position_slider is not None:
            self._position_slider.setRange(0, dur)

    def _on_slider_pressed(self) -> None:
        self._slider_dragging = True

    def _on_slider_released(self) -> None:
        self._slider_dragging = False
        if self._media_player is not None and self._position_slider is not None:
            self._media_player.setPosition(self._position_slider.value())

    def _on_media_error(self, _err, msg: str) -> None:
        from loguru import logger as log
        log.warning(f"QMediaPlayer error: {msg}")

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

    def _on_gen_image(self) -> None:
        self.save_requested.emit(self.scene.id, self._collect_updates())
        self.gen_image_requested.emit(self.scene.id)
        self.accept()

    def _on_gen_animation(self) -> None:
        self.save_requested.emit(self.scene.id, self._collect_updates())
        self.gen_animation_requested.emit(self.scene.id)
        self.accept()

    def _open_folder(self) -> None:
        path, _ = self._resolve_visual()
        if path is not None:
            try:
                os.startfile(str(path.parent))
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        if self._media_player is not None:
            try:
                self._media_player.stop()
                self._media_player.setSource(QUrl())
            except Exception:
                pass
        super().closeEvent(event)
