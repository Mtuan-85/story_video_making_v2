"""VideoPreviewDialog — focused on Video asset only.

Triggered when user clicks 🎬 button on a scene that has video.status='ready'.
For 'pending' state, main_window triggers Gen Video directly (no dialog).

Layout:
    [OpenCV-backed silent video preview]
    Script: (readonly)
    Image Prompt: (readonly — for context)
    Video Prompt: [textarea]
    [💾 Save] [🎬 Gen Video] [⚡ Fast] [📁 Folder] [Đóng]
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger as log
from PyQt6.QtCore import Qt, QElapsedTimer, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
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

PREVIEW_MAX_HEIGHT = 420
PLAYBACK_TIMER_MS = 15


class VideoPreviewDialog(QDialog):
    """Preview + edit dialog focused on Video asset.

    Shows a silent OpenCV-backed preview to avoid Qt Multimedia codec issues.
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

        self._capture = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_frame)
        self._timer.setInterval(PLAYBACK_TIMER_MS)
        self._play_clock = QElapsedTimer()
        self._position_slider: QSlider | None = None
        self._slider_dragging = False
        self._video_path: Path | None = None
        self._video_label: QLabel | None = None
        self._fps = 30.0
        self._frame_count = 0
        self._current_frame = 0
        self._play_start_frame = 0

        self.setWindowTitle(f"Video — {scene.id}")
        self.resize(880, 760)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 1. Video display
        self.visual_frame = QFrame()
        self.visual_frame.setMinimumHeight(PREVIEW_MAX_HEIGHT)
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

        self._video_label = QLabel()
        self._video_label.setFixedHeight(PREVIEW_MAX_HEIGHT)
        self._video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_label.setStyleSheet("background:#000; color:#aaa;")
        layout.addWidget(self._video_label, 1)

        if not self._open_capture(full):
            self._show_decode_fallback("OpenCV không đọc được video preview.")
            return

        controls = QHBoxLayout()
        b_play = QPushButton("▶ Play")
        b_play.clicked.connect(self._play)
        controls.addWidget(b_play)
        b_pause = QPushButton("⏸ Pause")
        b_pause.clicked.connect(self._pause)
        controls.addWidget(b_pause)
        b_stop = QPushButton("⏹ Stop")
        b_stop.clicked.connect(self._stop)
        controls.addWidget(b_stop)

        self._position_slider = QSlider(Qt.Orientation.Horizontal)
        self._position_slider.setRange(0, max(0, self._frame_count - 1))
        self._position_slider.sliderPressed.connect(self._on_slider_pressed)
        self._position_slider.sliderReleased.connect(self._on_slider_released)
        controls.addWidget(self._position_slider, 1)

        b_system = QPushButton("📺 Mở bằng player hệ thống")
        b_system.setToolTip("Mở MP4 bằng default player (nếu Qt không phát được)")
        b_system.clicked.connect(self._open_in_system_player)
        controls.addWidget(b_system)

        layout.addLayout(controls)
        self._show_frame(0)

    def _open_capture(self, path: Path) -> bool:
        try:
            import cv2

            self._capture = cv2.VideoCapture(str(path))
            if not self._capture.isOpened():
                return False
            fps = float(self._capture.get(cv2.CAP_PROP_FPS) or 0)
            frames = int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self._fps = fps if fps > 1 else 30.0
            self._frame_count = max(1, frames)
            return True
        except Exception as e:
            log.warning(f"OpenCV video preview init failed: {e}")
            return False

    def _show_frame(self, frame_index: int) -> None:
        if self._capture is None or self._video_label is None:
            return
        try:
            import cv2

            frame_index = max(0, min(frame_index, self._frame_count - 1))
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = self._capture.read()
            if not ok or frame is None:
                self._pause()
                return
            self._display_frame(frame, frame_index)
        except Exception as e:
            log.warning(f"OpenCV video preview frame failed: {e}")
            self._pause()

    def _display_frame(self, frame, frame_index: int) -> None:
        if self._video_label is None:
            return
        import cv2

        h, w = frame.shape[:2]
        if h > PREVIEW_MAX_HEIGHT:
            scale = PREVIEW_MAX_HEIGHT / h
            target_size = (max(1, int(w * scale)), PREVIEW_MAX_HEIGHT)
            frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(img)
        self._video_label.setPixmap(pix)
        self._current_frame = frame_index
        if self._position_slider is not None and not self._slider_dragging:
            self._position_slider.setValue(frame_index)

    def _skip_to_frame(self, frame_index: int) -> None:
        if self._capture is not None:
            import cv2

            self._capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

    def _read_next_frame(self, frame_index: int) -> bool:
        if self._capture is None:
            return False
        ok, frame = self._capture.read()
        if not ok or frame is None:
            return False
        self._display_frame(frame, frame_index)
        return True

    def _advance_frame(self) -> None:
        target_frame = self._play_start_frame + int(self._play_clock.elapsed() * self._fps / 1000)
        if target_frame <= self._current_frame:
            return
        if target_frame >= self._frame_count:
            self._pause()
            return
        if target_frame > self._current_frame + 1:
            self._skip_to_frame(target_frame)
        if not self._read_next_frame(target_frame):
            self._pause()

    def _play(self) -> None:
        if self._capture is not None:
            self._play_start_frame = self._current_frame
            self._play_clock.restart()
            self._timer.start()

    def _pause(self) -> None:
        self._timer.stop()

    def _stop(self) -> None:
        self._timer.stop()
        self._show_frame(0)

    def _on_slider_pressed(self) -> None:
        self._slider_dragging = True

    def _on_slider_released(self) -> None:
        self._slider_dragging = False
        if self._position_slider is not None:
            self._show_frame(self._position_slider.value())

    def _show_decode_fallback(self, msg: str) -> None:
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
            "⚠ <b>Không tạo được preview trong GUI</b><br>"
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
        self._timer.stop()
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
            self._capture = None
        super().closeEvent(event)
