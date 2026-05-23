"""VideoPreviewDialog — focused on Video asset only.

Triggered when user clicks 🎬 button on a scene that has video.status='ready'.
For 'pending' state, main_window triggers Gen Video directly (no dialog).

Layout:
    [Video player or codec-fallback]
    Script: (readonly)
    Image Prompt: (readonly — for context)
    Video Prompt: [textarea]
    [💾 Save] [🎬 Gen Video] [⚡ Fast] [📁 Folder] [Đóng]
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger as log
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class VideoPreviewDialog(QDialog):
    """Preview + edit dialog focused on Video asset.

    Shows video player (with codec fallback to system player).
    Image prompt is readonly (for context — user sees what generated the visual).
    Video prompt is editable.
    """

    save_requested = pyqtSignal(str, dict)             # (scene_id, updates)
    gen_animation_requested = pyqtSignal(str, bool)    # (scene_id, fast_mode)

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

        self._media_player: QMediaPlayer | None = None
        self._audio_output: QAudioOutput | None = None
        self._position_slider: QSlider | None = None
        self._slider_dragging = False
        self._video_path: Path | None = None

        self.setWindowTitle(f"Video — {scene.id}")
        self.resize(880, 760)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 1. Video display
        self.visual_frame = QFrame()
        self.visual_frame.setMinimumHeight(380)
        self.visual_frame.setStyleSheet("background:#000;")
        outer.addWidget(self.visual_frame, 1)
        self._load_video()

        # 2. Script (readonly)
        outer.addWidget(QLabel("<b>Script:</b> <i>(readonly)</i>"))
        self.story_view = QTextEdit()
        self.story_view.setPlainText(self.scene.script or "")
        self.story_view.setMaximumHeight(60)
        self.story_view.setReadOnly(True)
        self.story_view.setStyleSheet("background:#f5f5f5;")
        outer.addWidget(self.story_view)

        # 3. Image prompt (readonly — for context)
        outer.addWidget(QLabel("<b>Image Prompt:</b> <i>(readonly, để xem context khi sửa video prompt)</i>"))
        self.image_prompt_view = QTextEdit()
        self.image_prompt_view.setPlainText(self.scene.imagePrompt or "")
        self.image_prompt_view.setMaximumHeight(80)
        self.image_prompt_view.setReadOnly(True)
        self.image_prompt_view.setStyleSheet("background:#f5f5f5;")
        outer.addWidget(self.image_prompt_view)

        # 4. Video prompt (editable)
        outer.addWidget(QLabel("<b>Video Prompt:</b>"))
        self.video_prompt_edit = QTextEdit()
        self.video_prompt_edit.setPlainText(self.scene.videoPrompt or "")
        self.video_prompt_edit.setMaximumHeight(100)
        outer.addWidget(self.video_prompt_edit)

        # 5. Buttons
        btns = QHBoxLayout()

        b_save = QPushButton("💾 Save")
        b_save.clicked.connect(self._on_save)
        btns.addWidget(b_save)

        b_gen = QPushButton("🎬 Gen Video")
        b_gen.setToolTip("Save + regenerate video (provider/model)")
        b_gen.clicked.connect(self._on_gen_video)
        btns.addWidget(b_gen)

        self.fast_check = QCheckBox("⚡ Fast")
        self.fast_check.setToolTip(
            "Fast mode: paste prompt + wait 5s instead of typing each char."
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

    # ------------------------------------------------------------------
    # Video loading
    # ------------------------------------------------------------------

    def _load_video(self) -> None:
        layout = QVBoxLayout(self.visual_frame)
        layout.setContentsMargins(0, 0, 0, 0)

        vid_state = self.scene_state.get("video", {})
        path = vid_state.get("path")
        if path is None or vid_state.get("status") != "ready":
            label = QLabel("(Chưa có video — bấm Gen Video)")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color:#999;")
            layout.addWidget(label)
            return

        full = self._abs(path)
        self._video_path = full
        if not full.exists():
            label = QLabel(f"(File không tồn tại: {path})")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color:#999;")
            layout.addWidget(label)
            return

        # Try QMediaPlayer; if it errors, fall back to system player button
        video_widget = QVideoWidget()
        video_widget.setMinimumHeight(360)
        video_widget.setStyleSheet("background:#000;")
        layout.addWidget(video_widget, 1)

        self._media_player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.setVideoOutput(video_widget)
        self._media_player.setSource(QUrl.fromLocalFile(str(full)))

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

        b_system = QPushButton("📺 Mở bằng player hệ thống")
        b_system.setToolTip("Mở MP4 bằng default player (nếu Qt không phát được)")
        b_system.clicked.connect(self._open_in_system_player)
        controls.addWidget(b_system)

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
        """Qt couldn't play the video — show a clear codec fallback message."""
        log.warning(f"QMediaPlayer error: {msg}")
        # Replace video widget area with codec warning + system player button
        layout = self.visual_frame.layout()
        if layout is None:
            return

        # Clear existing
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        warn = QLabel(
            "⚠ <b>Qt không phát được video</b> (thiếu codec H.264 hoặc MP4 không hợp lệ)<br>"
            f"<small>{msg}</small>"
        )
        warn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        warn.setStyleSheet("color:#fff; padding:20px;")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        b_system = QPushButton("📺 Mở bằng player hệ thống")
        b_system.setMinimumHeight(40)
        b_system.clicked.connect(self._open_in_system_player)
        layout.addWidget(b_system, alignment=Qt.AlignmentFlag.AlignCenter)

    def _open_in_system_player(self) -> None:
        if self._video_path and self._video_path.exists():
            try:
                os.startfile(str(self._video_path))
            except Exception as e:
                log.error(f"Open in system player failed: {e}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _abs(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        return p if p.is_absolute() else self.project_root / p

    def _collect_updates(self) -> dict:
        return {
            "videoPrompt": self.video_prompt_edit.toPlainText().strip() or None,
        }

    def _on_save(self) -> None:
        self.save_requested.emit(self.scene.id, self._collect_updates())
        self.accept()

    def _on_gen_video(self) -> None:
        self.save_requested.emit(self.scene.id, self._collect_updates())
        self.gen_animation_requested.emit(self.scene.id, self.fast_check.isChecked())
        self.accept()

    def _open_folder(self) -> None:
        if self._video_path:
            try:
                os.startfile(str(self._video_path.parent))
            except Exception:
                pass
        else:
            try:
                os.startfile(str(self.project_root / "sources"))
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
