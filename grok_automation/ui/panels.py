from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from grok.prompt_loader import load_prompts


class ConnectionPanel(QGroupBox):
    connect_requested = pyqtSignal(str)
    disconnect_requested = pyqtSignal()
    refresh_tabs_requested = pyqtSignal()
    tab_selected = pyqtSignal(int)

    def __init__(self, default_cdp_url: str = "http://localhost:9222", parent: QWidget | None = None) -> None:
        super().__init__("Kết nối Chrome (CDP)", parent)
        self._build_ui(default_cdp_url)
        self._wire()
        self.set_state(connected=False)

    def _build_ui(self, default_cdp_url: str) -> None:
        layout = QVBoxLayout(self)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("CDP URL:"))
        self.url_edit = QLineEdit(default_cdp_url)
        self.url_edit.setPlaceholderText("http://localhost:9222")
        url_row.addWidget(self.url_edit, 1)
        self.btn_connect = QPushButton("Kết nối")
        self.btn_disconnect = QPushButton("Ngắt kết nối")
        url_row.addWidget(self.btn_connect)
        url_row.addWidget(self.btn_disconnect)
        layout.addLayout(url_row)

        tab_row = QHBoxLayout()
        tab_row.addWidget(QLabel("Tab Grok:"))
        self.tab_combo = QComboBox()
        self.tab_combo.setMinimumWidth(360)
        tab_row.addWidget(self.tab_combo, 1)
        self.btn_refresh = QPushButton("Làm mới")
        tab_row.addWidget(self.btn_refresh)
        layout.addLayout(tab_row)

        self.status_label = QLabel("Trạng thái: chưa kết nối")
        layout.addWidget(self.status_label)

    def _wire(self) -> None:
        self.btn_connect.clicked.connect(
            lambda: self.connect_requested.emit(self.url_edit.text().strip())
        )
        self.btn_disconnect.clicked.connect(self.disconnect_requested.emit)
        self.btn_refresh.clicked.connect(self.refresh_tabs_requested.emit)
        self.tab_combo.activated.connect(self._on_tab_activated)

    def _on_tab_activated(self, idx: int) -> None:
        if idx < 0:
            return
        page_index = self.tab_combo.itemData(idx)
        if page_index is None:
            return
        self.tab_selected.emit(int(page_index))

    def set_state(self, *, connected: bool) -> None:
        self.btn_connect.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        self.btn_refresh.setEnabled(connected)
        self.tab_combo.setEnabled(connected)
        self.url_edit.setEnabled(not connected)

    def set_status(self, text: str) -> None:
        self.status_label.setText(f"Trạng thái: {text}")

    def populate_tabs(self, tabs: list[dict[str, str]]) -> None:
        self.tab_combo.clear()
        if not tabs:
            self.tab_combo.addItem("(không tìm thấy tab Grok)", None)
            self.tab_combo.setEnabled(False)
            return
        self.tab_combo.setEnabled(True)
        for tab in tabs:
            label = f"{tab.get('title', '(untitled)')} — {tab.get('url', '')}"
            self.tab_combo.addItem(label, int(tab["index"]))


class GenerationPanel(QGroupBox):
    """All generation settings driven by UI controls.

    JSON only contains prompts; everything else (mode, quality, aspect, refs,
    pick mode, typing speed, timeout, project name) is set here.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Cài đặt generation", parent)
        self.prompts: list[dict] = []
        self.ref_cache: dict[str, Path] = {}
        self._build_ui()
        self._update_visibility()

    def _build_ui(self) -> None:
        form = QFormLayout(self)

        # 1. Type radio
        self.type_image = QRadioButton("Image")
        self.type_video = QRadioButton("Video")
        self.type_image.setChecked(True)
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self.type_image)
        self._type_group.addButton(self.type_video)
        self._type_group.buttonClicked.connect(lambda *_: self._update_visibility())
        type_row = QHBoxLayout()
        type_row.addWidget(self.type_image)
        type_row.addWidget(self.type_video)
        type_row.addStretch(1)
        form.addRow("Loại:", self._wrap(type_row))

        # 2. Quality radio (image only)
        self.quality_speed = QRadioButton("Speed")
        self.quality_quality = QRadioButton("Quality")
        self.quality_quality.setChecked(True)
        self._quality_group = QButtonGroup(self)
        self._quality_group.addButton(self.quality_speed)
        self._quality_group.addButton(self.quality_quality)
        q_row = QHBoxLayout()
        q_row.addWidget(self.quality_speed)
        q_row.addWidget(self.quality_quality)
        q_row.addStretch(1)
        self.quality_label = QLabel("Quality:")
        form.addRow(self.quality_label, self._wrap(q_row))
        self._quality_row_widget = form.itemAt(form.rowCount() - 1, QFormLayout.ItemRole.FieldRole).widget()

        # 3. Aspect dropdown
        self.aspect = QComboBox()
        self.aspect.addItems(["16:9", "9:16", "1:1", "3:2", "2:3"])
        self.aspect.setCurrentText("16:9")
        form.addRow("Aspect:", self.aspect)

        # 4. Resolution radio (video only)
        self.res_480 = QRadioButton("480p")
        self.res_720 = QRadioButton("720p")
        self.res_720.setChecked(True)
        self._res_group = QButtonGroup(self)
        self._res_group.addButton(self.res_480)
        self._res_group.addButton(self.res_720)
        r_row = QHBoxLayout()
        r_row.addWidget(self.res_480)
        r_row.addWidget(self.res_720)
        r_row.addStretch(1)
        self.res_label = QLabel("Resolution:")
        form.addRow(self.res_label, self._wrap(r_row))
        self._res_row_widget = form.itemAt(form.rowCount() - 1, QFormLayout.ItemRole.FieldRole).widget()

        # 5. Duration radio (video only)
        self.dur_6 = QRadioButton("6s")
        self.dur_10 = QRadioButton("10s")
        self.dur_6.setChecked(True)
        self._dur_group = QButtonGroup(self)
        self._dur_group.addButton(self.dur_6)
        self._dur_group.addButton(self.dur_10)
        d_row = QHBoxLayout()
        d_row.addWidget(self.dur_6)
        d_row.addWidget(self.dur_10)
        d_row.addStretch(1)
        self.dur_label = QLabel("Duration:")
        form.addRow(self.dur_label, self._wrap(d_row))
        self._dur_row_widget = form.itemAt(form.rowCount() - 1, QFormLayout.ItemRole.FieldRole).widget()

        # 6. Pick mode (image only)
        self.pick_auto = QRadioButton("Auto (ảnh đầu tiên)")
        self.pick_claude = QRadioButton("Claude pick")
        self.pick_auto.setChecked(True)
        self._pick_group = QButtonGroup(self)
        self._pick_group.addButton(self.pick_auto)
        self._pick_group.addButton(self.pick_claude)
        p_row = QHBoxLayout()
        p_row.addWidget(self.pick_auto)
        p_row.addWidget(self.pick_claude)
        p_row.addStretch(1)
        self.pick_label = QLabel("Pick mode:")
        form.addRow(self.pick_label, self._wrap(p_row))
        self._pick_row_widget = form.itemAt(form.rowCount() - 1, QFormLayout.ItemRole.FieldRole).widget()

        # 7. Typing speed
        self.speed_fast = QRadioButton("Fast")
        self.speed_human = QRadioButton("Human")
        self.speed_slow = QRadioButton("Slow")
        self.speed_fast.setChecked(True)
        self._speed_group = QButtonGroup(self)
        self._speed_group.addButton(self.speed_fast)
        self._speed_group.addButton(self.speed_human)
        self._speed_group.addButton(self.speed_slow)
        s_row = QHBoxLayout()
        s_row.addWidget(self.speed_fast)
        s_row.addWidget(self.speed_human)
        s_row.addWidget(self.speed_slow)
        s_row.addStretch(1)
        form.addRow("Tốc độ gõ:", self._wrap(s_row))

        # 8. Wait timeout
        self.timeout_input = QSpinBox()
        self.timeout_input.setRange(30, 600)
        self.timeout_input.setValue(60)
        self.timeout_input.setSuffix(" s")
        form.addRow("Timeout đợi:", self.timeout_input)

        # 9. Project name
        self.project_input = QLineEdit()
        self.project_input.setPlaceholderText("vd: eiffel_test")
        form.addRow("Project name:", self.project_input)

        # 10. Ref folder
        ref_row = QHBoxLayout()
        self.ref_folder_input = QLineEdit()
        self.ref_folder_input.setPlaceholderText("D:/grok_refs/")
        self.ref_folder_btn = QPushButton("📁 Chọn")
        self.ref_folder_btn.clicked.connect(self._browse_ref_folder)
        ref_row.addWidget(self.ref_folder_input, 1)
        ref_row.addWidget(self.ref_folder_btn)
        form.addRow("Ref folder:", self._wrap(ref_row))

        # 11. Prompts JSON
        prompts_row = QHBoxLayout()
        self.prompts_input = QLineEdit()
        self.prompts_input.setReadOnly(True)
        self.prompts_btn = QPushButton("📂 Tải")
        self.prompts_btn.clicked.connect(self._load_prompts_dialog)
        prompts_row.addWidget(self.prompts_input, 1)
        prompts_row.addWidget(self.prompts_btn)
        form.addRow("Prompts JSON:", self._wrap(prompts_row))

        self.prompts_status = QLabel("Chưa load prompts")
        form.addRow("", self.prompts_status)

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _update_visibility(self) -> None:
        is_image = self.type_image.isChecked()
        # Quality / Pick mode rows visible only for image
        for w in (self.quality_label, self._quality_row_widget,
                  self.pick_label, self._pick_row_widget):
            w.setVisible(is_image)
        # Resolution / Duration rows visible only for video
        for w in (self.res_label, self._res_row_widget,
                  self.dur_label, self._dur_row_widget):
            w.setVisible(not is_image)

    def _browse_ref_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Chọn ref folder", str(Path.cwd())
        )
        if folder:
            self.ref_folder_input.setText(folder)
            self._scan_ref_folder(folder)

    def _scan_ref_folder(self, folder: str) -> None:
        p = Path(folder)
        if not p.is_dir():
            self.ref_cache = {}
            return
        exts = {".jpg", ".jpeg", ".png", ".webp"}
        self.ref_cache = {
            f.name: f for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in exts
        }
        logger.info(f"Scanned {len(self.ref_cache)} ref images in {folder}")

    def _load_prompts_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file prompts JSON",
            str(Path.cwd() / "examples"), "JSON (*.json)"
        )
        if not path:
            return
        try:
            self.prompts = load_prompts(Path(path))
            self.prompts_input.setText(path)
            n_with_ref = sum(1 for p in self.prompts if p.get("ref"))
            self.prompts_status.setText(
                f"✓ {len(self.prompts)} prompts ({n_with_ref} có ref)"
            )
        except Exception as e:
            self.prompts = []
            self.prompts_status.setText(f"❌ Lỗi: {e}")

    def get_settings(self) -> dict[str, Any]:
        if self.speed_fast.isChecked():
            typing = "fast"
        elif self.speed_slow.isChecked():
            typing = "slow"
        else:
            typing = "human"
        return {
            "type": "image" if self.type_image.isChecked() else "video",
            "quality": "speed" if self.quality_speed.isChecked() else "quality",
            "aspect": self.aspect.currentText(),
            "resolution": "480p" if self.res_480.isChecked() else "720p",
            "duration": "6s" if self.dur_6.isChecked() else "10s",
            "pick_mode": "auto" if self.pick_auto.isChecked() else "claude",
            "typing_speed": typing,
            "wait_timeout_s": self.timeout_input.value(),
            "project_name": self.project_input.text().strip(),
            "ref_folder": self.ref_folder_input.text().strip(),
            "ref_cache": dict(self.ref_cache),
            "prompts": list(self.prompts),
        }


class RunPanel(QGroupBox):
    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Chạy", parent)
        layout = QHBoxLayout(self)
        self.btn_start = QPushButton("▶ Bắt đầu")
        self.btn_stop = QPushButton("■ Dừng")
        self.status = QLabel("Sẵn sàng")
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.status, 1)

        self.btn_start.clicked.connect(self.start_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)

        self.set_running(False)

    def set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def set_status(self, text: str) -> None:
        self.status.setText(text)


class LogPanel(QGroupBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Log", parent)
        layout = QVBoxLayout(self)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(2000)
        layout.addWidget(self.view)

    def append(self, msg: str) -> None:
        self.view.appendPlainText(msg)
