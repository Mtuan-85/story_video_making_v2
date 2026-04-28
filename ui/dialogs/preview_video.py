"""Preview video dialog — embedded HTML5-style player via QMediaPlayer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
)


class PreviewVideoDialog(QDialog):
    """Modal preview for a video clip.

    Signals:
        regen_requested(scene_id) — user wants to re-generate this clip.
    """

    regen_requested = pyqtSignal(str)

    def __init__(self, scene_id: str, video_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.scene_id = scene_id
        self.video_path = Path(video_path)

        self.setWindowTitle(f"Preview video — {scene_id}")
        self.setModal(True)

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.audio_out.setVolume(0.7)

        self._build_ui()
        self._load_video()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_widget.setStyleSheet("background:#000")
        self.player.setVideoOutput(self.video_widget)
        outer.addWidget(self.video_widget, 1)

        # Transport controls
        ctrl = QHBoxLayout()
        self.btn_play = QPushButton("▶ Play")
        self.btn_play.clicked.connect(self._toggle_play)
        ctrl.addWidget(self.btn_play)

        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(0, 0)
        self.position.sliderMoved.connect(self.player.setPosition)
        ctrl.addWidget(self.position, 1)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setMinimumWidth(80)
        ctrl.addWidget(self.time_label)
        outer.addLayout(ctrl)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state_changed)

        # Path footer
        path_label = QLabel(str(self.video_path))
        path_label.setStyleSheet("color:#666; font-family:Consolas,monospace; font-size:11px;")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(path_label)

        # Action row
        btn_row = QHBoxLayout()
        btn_open = QPushButton("📂 Mở thư mục")
        btn_open.clicked.connect(self._open_folder)
        btn_row.addWidget(btn_open)

        btn_regen = QPushButton("🔄 Re-gen video")
        btn_regen.clicked.connect(self._on_regen)
        btn_row.addWidget(btn_regen)

        btn_row.addStretch()
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        outer.addLayout(btn_row)

        # Reasonable starting size
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(int(avail.width() * 0.5), int(avail.height() * 0.55))
        else:
            self.resize(720, 540)

    def _load_video(self) -> None:
        if not self.video_path.exists():
            self.time_label.setText("(file không tồn tại)")
            return
        self.player.setSource(QUrl.fromLocalFile(str(self.video_path.resolve())))

    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_position(self, ms: int) -> None:
        self.position.blockSignals(True)
        self.position.setValue(ms)
        self.position.blockSignals(False)
        self.time_label.setText(f"{_fmt_time(ms)} / {_fmt_time(self.player.duration())}")

    def _on_duration(self, ms: int) -> None:
        self.position.setRange(0, ms)
        self.time_label.setText(f"{_fmt_time(self.player.position())} / {_fmt_time(ms)}")

    def _on_state_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("⏸ Pause" if playing else "▶ Play")

    def _open_folder(self) -> None:
        folder = self.video_path.parent
        if not folder.exists():
            return
        try:
            if os.name == "nt":
                subprocess.run(["explorer", "/select,", str(self.video_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
        except Exception:
            pass

    def _on_regen(self) -> None:
        self.player.stop()
        self.regen_requested.emit(self.scene_id)
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.player.stop()
        super().closeEvent(event)


def _fmt_time(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60}:{s % 60:02d}"
