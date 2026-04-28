"""
Main UI window v3 - ultra minimal.
Bỏ field "Số objects" - Claude tự group thông minh.
"""

from pathlib import Path

from PyQt6.QtCore import Qt, QSettings, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QRadioButton, QButtonGroup,
    QFileDialog, QTextEdit, QMessageBox, QInputDialog, QFrame,
)

from worker import GenerationWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Slideshow Generator v3")
        self.setMinimumSize(680, 620)

        self.settings = QSettings("SlideshowApp", "Generator_v3")
        self.worker = None
        self.last_output: Path = None

        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("🎬 AI Slideshow Generator")
        tf = QFont(); tf.setPointSize(16); tf.setBold(True)
        title.setFont(tf)
        root.addWidget(title)

        subtitle = QLabel(
            "Claude tự phân tích scene, group objects thông minh, design animation show đẹp.\n"
            "Chỉ cần chuẩn bị 1 ảnh scene (bg đơn + objects) và chọn duration."
        )
        subtitle.setStyleSheet("color: gray;")
        root.addWidget(subtitle)

        root.addWidget(self._hline())

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)

        # Folder
        form.addWidget(QLabel("Folder chứa scene:"), 0, 0)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Folder có 1 file scene (tên bất kỳ)")
        form.addWidget(self.folder_input, 0, 1)
        browse = QPushButton("📁 Browse...")
        browse.clicked.connect(self._browse_folder)
        form.addWidget(browse, 0, 2)

        # Duration
        form.addWidget(QLabel("Duration:"), 1, 0)
        self.duration_input = QSpinBox()
        self.duration_input.setRange(2, 120)
        self.duration_input.setValue(5)
        self.duration_input.setSuffix(" giây")
        dur_row = QHBoxLayout()
        dur_row.addWidget(self.duration_input)
        dur_row.addWidget(QLabel(" (Claude sẽ chia pacing trong khoảng thời gian này)"))
        dur_row.addStretch()
        dur_w = QWidget(); dur_w.setLayout(dur_row)
        form.addWidget(dur_w, 1, 1, 1, 2)

        # Preset
        form.addWidget(QLabel("Preset:"), 2, 0)
        self.preset_youtube = QRadioButton("YouTube (1920×1080)")
        self.preset_tiktok = QRadioButton("TikTok (1080×1920)")
        self.preset_youtube.setChecked(True)
        self.preset_group = QButtonGroup()
        self.preset_group.addButton(self.preset_youtube)
        self.preset_group.addButton(self.preset_tiktok)
        pr = QHBoxLayout()
        pr.addWidget(self.preset_youtube)
        pr.addWidget(self.preset_tiktok)
        pr.addStretch()
        pw = QWidget(); pw.setLayout(pr)
        form.addWidget(pw, 2, 1, 1, 2)

        # BG removal method
        form.addWidget(QLabel("Xóa BG:"), 3, 0)
        self.bg_auto = QRadioButton("Auto (khuyên dùng)")
        self.bg_chroma = QRadioButton("Chroma (giữ text)")
        self.bg_rembg = QRadioButton("AI rembg")
        self.bg_auto.setChecked(True)
        self.bg_group = QButtonGroup()
        self.bg_group.addButton(self.bg_auto)
        self.bg_group.addButton(self.bg_chroma)
        self.bg_group.addButton(self.bg_rembg)
        bgr = QHBoxLayout()
        bgr.addWidget(self.bg_auto)
        bgr.addWidget(self.bg_chroma)
        bgr.addWidget(self.bg_rembg)
        bgr.addStretch()
        bw = QWidget(); bw.setLayout(bgr)
        form.addWidget(bw, 3, 1, 1, 2)

        root.addLayout(form)

        self.generate_btn = QPushButton("⚡ Generate")
        self.generate_btn.setMinimumHeight(44)
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed; color: white;
                font-size: 14px; font-weight: bold;
                border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #6d28d9; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.generate_btn.clicked.connect(self._on_generate)
        root.addWidget(self.generate_btn)

        root.addWidget(self._hline())

        sl = QLabel("Status:")
        sl.setStyleSheet("font-weight: bold;")
        root.addWidget(sl)

        self.status_view = QTextEdit()
        self.status_view.setReadOnly(True)
        self.status_view.setMinimumHeight(220)
        self.status_view.setStyleSheet("""
            QTextEdit {
                background-color: #1e293b; color: #e2e8f0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px; border-radius: 6px; padding: 8px;
            }
        """)
        self.status_view.setPlaceholderText(
            "Sẵn sàng. Chuẩn bị folder có 1 ảnh scene (bg đơn + nhiều objects) rồi click Generate."
        )
        root.addWidget(self.status_view)

        self.result_widget = QWidget()
        rl = QVBoxLayout(self.result_widget)
        rl.setContentsMargins(0, 0, 0, 0)

        self.result_label = QLabel()
        self.result_label.setOpenExternalLinks(False)
        self.result_label.linkActivated.connect(self._open_path)
        self.result_label.setStyleSheet(
            "padding: 8px; background-color: #ecfdf5; border-radius: 6px;"
        )
        self.result_label.setWordWrap(True)
        rl.addWidget(self.result_label)

        br = QHBoxLayout()
        self.regenerate_btn = QPushButton("🔄 Re-generate (với hint)")
        self.regenerate_btn.clicked.connect(self._on_regenerate)
        br.addWidget(self.regenerate_btn)

        self.open_folder_btn = QPushButton("📂 Mở folder kết quả")
        self.open_folder_btn.clicked.connect(self._open_output_folder)
        br.addWidget(self.open_folder_btn)
        br.addStretch()
        rl.addLayout(br)

        self.result_widget.hide()
        root.addWidget(self.result_widget)

        root.addStretch()

    def _hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _browse_folder(self):
        last = self.settings.value("last_folder", str(Path.home()))
        folder = QFileDialog.getExistingDirectory(
            self, "Chọn folder chứa scene image", last
        )
        if folder:
            self.folder_input.setText(folder)

    def _get_preset(self):
        return "youtube" if self.preset_youtube.isChecked() else "tiktok"

    def _get_bg_method(self):
        if self.bg_chroma.isChecked():
            return "chroma"
        if self.bg_rembg.isChecked():
            return "rembg"
        return "auto"

    def _on_generate(self, checked=False, hint: str = ""):
        folder = self.folder_input.text().strip()
        if not folder:
            QMessageBox.warning(self, "Thiếu folder", "Chọn folder trước.")
            return

        folder_path = Path(folder)
        if not folder_path.exists():
            QMessageBox.warning(self, "Folder lỗi", f"{folder} không tồn tại.")
            return

        self.settings.setValue("last_folder", folder)
        self.settings.setValue("last_duration", self.duration_input.value())
        self.settings.setValue("last_preset", self._get_preset())
        self.settings.setValue("last_bg_method", self._get_bg_method())

        self.status_view.clear()
        self.result_widget.hide()
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("⏳ Đang xử lý...")

        self.worker = GenerationWorker(
            folder=folder_path,
            duration=self.duration_input.value(),
            preset=self._get_preset(),
            hint=hint,
            bg_method=self._get_bg_method(),
        )
        self.worker.status.connect(self._append_status)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_regenerate(self):
        hint, ok = QInputDialog.getMultiLineText(
            self, "Re-generate với hint",
            "Bạn muốn Claude điều chỉnh gì?\n"
            "(VD: 'nhiều group hơn', 'animation chậm lại', "
            "'object 1 và 2 nên tách riêng, không cùng scene'...)",
            ""
        )
        if ok and hint.strip():
            self._on_generate(hint=hint.strip())

    def _open_output_folder(self):
        if self.last_output and self.last_output.parent.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output.parent)))

    def _open_path(self, link: str):
        QDesktopServices.openUrl(QUrl(link))

    def _append_status(self, msg: str):
        self.status_view.append(msg)
        cursor = self.status_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.status_view.setTextCursor(cursor)

    def _on_done(self, output_path: Path):
        self.last_output = output_path
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("⚡ Generate")

        size_mb = output_path.stat().st_size / (1024 * 1024)
        folder_url = QUrl.fromLocalFile(str(output_path.parent)).toString()
        file_url = QUrl.fromLocalFile(str(output_path)).toString()

        self.result_label.setText(
            f"✅ <b>Render xong!</b><br>"
            f"📄 <a href='{file_url}'>{output_path.name}</a> ({size_mb:.1f} MB)<br>"
            f"📂 <a href='{folder_url}'>{output_path.parent}</a>"
        )
        self.result_widget.show()

    def _on_failed(self, error: str):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("⚡ Generate")
        self._append_status(f"\n❌ LỖI: {error}")
        QMessageBox.critical(self, "Lỗi", error.split("\n")[0])

    def _load_settings(self):
        last_folder = self.settings.value("last_folder", "")
        if last_folder:
            self.folder_input.setText(last_folder)
        self.duration_input.setValue(
            self.settings.value("last_duration", 5, type=int)
        )
        if self.settings.value("last_preset", "youtube") == "tiktok":
            self.preset_tiktok.setChecked(True)
        else:
            self.preset_youtube.setChecked(True)

        last_bg = self.settings.value("last_bg_method", "auto")
        if last_bg == "chroma":
            self.bg_chroma.setChecked(True)
        elif last_bg == "rembg":
            self.bg_rembg.setChecked(True)
        else:
            self.bg_auto.setChecked(True)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "Đang xử lý",
                "Worker đang chạy. Đóng sẽ hủy. Tiếp tục?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.terminate()
            self.worker.wait(2000)
        event.accept()
