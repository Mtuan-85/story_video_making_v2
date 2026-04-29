"""Edit prompt dialog — story / image prompt / video prompt / visual_type / duration.

Returns the edited Scene fields via accepted_data() property after .exec().
The caller is responsible for persisting back to scenes.json.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from core.schema import Scene

VISUAL_TYPES = [
    "image_grok",
    "video_grok",
    "slideshow",
    "ken_burns_self",
    "ken_burns_cont",
]


class PromptEditorDialog(QDialog):
    """Modal editor for one Scene's prompts + meta.

    Two-button save:
        save_only      — just persist (Save)
        save_and_regen — persist + ask caller to re-gen image (Save & Re-gen)

    Caller pattern:
        dlg = PromptEditorDialog(scene)
        result = dlg.exec()  # 0 = cancel, 1 = save, 2 = save_and_regen
        if result:
            updates = dlg.collected_updates()
            ... apply to scenes.json + project.scenes_json ...
    """

    SAVE_ONLY = 1
    SAVE_AND_REGEN = 2

    def __init__(self, scene: Scene, parent=None) -> None:
        super().__init__(parent)
        self.scene = scene
        self._result_kind = 0
        self.setWindowTitle(f"Sửa prompts — {scene.id}")
        self.setModal(True)
        self.resize(720, 640)
        self._build_ui()
        self._populate(scene)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        # Story (vi)
        self.story_vi = QPlainTextEdit()
        self.story_vi.setPlaceholderText("Nội dung tiếng Việt — dùng cho voice + subtitle")
        self.story_vi.setMinimumHeight(80)
        form.addRow("Story (vi):", self.story_vi)

        # Story (en) — optional
        self.story_en = QPlainTextEdit()
        self.story_en.setPlaceholderText("(Tùy chọn) phiên bản tiếng Anh")
        self.story_en.setMinimumHeight(60)
        form.addRow("Story (en):", self.story_en)

        # Image prompt
        self.image_prompt = QPlainTextEdit()
        self.image_prompt.setPlaceholderText("Prompt gen ảnh Grok")
        self.image_prompt.setMinimumHeight(100)
        form.addRow("Image prompt:", self.image_prompt)

        # Video prompt + enable toggle
        video_box = QVBoxLayout()
        self.video_enable = QCheckBox("Bật video prompt")
        self.video_enable.toggled.connect(self._on_video_toggled)
        video_box.addWidget(self.video_enable)
        self.video_prompt = QPlainTextEdit()
        self.video_prompt.setPlaceholderText("Prompt cho image-to-video (chỉ dùng nếu visual_type = video_grok)")
        self.video_prompt.setMinimumHeight(80)
        video_box.addWidget(self.video_prompt)
        form.addRow("Video prompt:", video_box)

        # Emotion (Fish Audio)
        self.emotion = QLineEdit()
        self.emotion.setPlaceholderText("(Tùy chọn) — vd: 'calm warm narrator tone'")
        form.addRow("Emotion:", self.emotion)

        # Visual type
        self.visual_type = QComboBox()
        for v in VISUAL_TYPES:
            self.visual_type.addItem(v)
        form.addRow("Visual type:", self.visual_type)

        # Duration
        self.duration = QSpinBox()
        self.duration.setRange(1, 60)
        self.duration.setSuffix(" giây")
        form.addRow("Duration:", self.duration)

        outer.addLayout(form)
        outer.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("💾 Lưu")
        btn_save.clicked.connect(lambda: self._on_save(self.SAVE_ONLY))
        btn_row.addWidget(btn_save)

        btn_save_regen = QPushButton("💾 Lưu & Re-gen ảnh")
        btn_save_regen.setStyleSheet("font-weight:bold")
        btn_save_regen.clicked.connect(lambda: self._on_save(self.SAVE_AND_REGEN))
        btn_row.addWidget(btn_save_regen)

        outer.addLayout(btn_row)

    def _populate(self, scene: Scene) -> None:
        self.story_vi.setPlainText(scene.story_vi or "")
        self.story_en.setPlainText(scene.story_en or "")
        self.image_prompt.setPlainText(scene.imagePrompt)
        self.video_prompt.setPlainText(scene.videoPrompt or "")
        has_video = scene.videoPrompt is not None
        self.video_enable.setChecked(has_video)
        self.video_prompt.setEnabled(has_video)
        self.emotion.setText(scene.emotion or "")
        self.visual_type.setCurrentText(scene.visual_type)
        self.duration.setValue(scene.duration)

    def _on_video_toggled(self, checked: bool) -> None:
        self.video_prompt.setEnabled(checked)

    def _on_save(self, kind: int) -> None:
        story_vi = self.story_vi.toPlainText().strip()
        story_en = self.story_en.toPlainText().strip()
        if not story_vi and not story_en:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Thiếu nội dung",
                "Phải có ít nhất story_vi hoặc story_en",
            )
            return
        if not self.image_prompt.toPlainText().strip():
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Thiếu prompt", "imagePrompt không được rỗng")
            return
        self._result_kind = kind
        self.accept()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def result_kind(self) -> int:
        """0 = cancel, 1 = save_only, 2 = save_and_regen."""
        return self._result_kind

    def collected_updates(self) -> dict[str, Any]:
        video_text = self.video_prompt.toPlainText().strip()
        return {
            "story_vi": self.story_vi.toPlainText().strip() or None,
            "story_en": self.story_en.toPlainText().strip() or None,
            "imagePrompt": self.image_prompt.toPlainText().strip(),
            "videoPrompt": video_text if (self.video_enable.isChecked() and video_text) else None,
            "emotion": self.emotion.text().strip() or None,
            "visual_type": self.visual_type.currentText(),
            "duration": self.duration.value(),
        }
