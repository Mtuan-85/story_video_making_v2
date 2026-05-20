"""Provider/model/CDP health panel.

The GUI does not own browser/CDP objects. Image generation receives this
configuration and runs in a worker process.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request

from loguru import logger as log
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_CDP_URL = "http://127.0.0.1:9222"


class ConnectionPanel(QGroupBox):
    page_ready = pyqtSignal(object)
    disconnected = pyqtSignal()
    log_message = pyqtSignal(str)
    _cdp_check_done = pyqtSignal(bool, str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Provider", parent)
        self._cdp_healthy = False
        self._build_ui()
        self._cdp_check_done.connect(self._on_cdp_check_done)
        self._update_status("CDP chưa kiểm tra", healthy=False)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Provider:"))
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Grok", "grok")
        self.provider_combo.setEnabled(False)
        row1.addWidget(self.provider_combo)

        row1.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItem("Grok auto", "grok-auto")
        self.model_combo.setEnabled(False)
        row1.addWidget(self.model_combo)
        row1.addStretch()
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("CDP URL:"))
        self.url_edit = QLineEdit(DEFAULT_CDP_URL)
        self.url_edit.setMinimumWidth(260)
        self.url_edit.textChanged.connect(self._on_url_changed)
        row2.addWidget(self.url_edit)

        self.btn_check = QPushButton("Check CDP")
        self.btn_check.clicked.connect(self._check_cdp)
        row2.addWidget(self.btn_check)

        self.status_label = QLabel()
        self.status_label.setMinimumWidth(220)
        row2.addWidget(self.status_label)
        row2.addStretch()
        outer.addLayout(row2)

    def selected_provider(self) -> str:
        return "grok"

    def selected_model(self) -> str:
        return "grok-auto"

    def cdp_url(self) -> str:
        return self.url_edit.text().strip() or DEFAULT_CDP_URL

    def get_url(self) -> str:
        return self.cdp_url()

    def is_connected(self) -> bool:
        return self._cdp_healthy

    def _emit(self, msg: str) -> None:
        log.info(msg)
        self.log_message.emit(msg)

    def _on_url_changed(self) -> None:
        if self._cdp_healthy:
            self._update_status("CDP chưa kiểm tra", healthy=False)

    def _update_status(self, text: str, healthy: bool) -> None:
        self._cdp_healthy = healthy
        color = "#27ae60" if healthy else "#c0392b"
        self.status_label.setText(f'<span style="color:{color}">●</span> {text}')

    def _check_cdp(self) -> None:
        url = self.cdp_url().rstrip("/")
        version_url = f"{url}/json/version"
        self.btn_check.setEnabled(False)
        self._update_status("Đang check CDP...", healthy=False)

        def worker() -> None:
            healthy = False
            status = "CDP unreachable"
            message = ""
            try:
                with urllib.request.urlopen(version_url, timeout=2) as resp:
                    if 200 <= resp.status < 300:
                        healthy = True
                        status = "CDP reachable"
                        message = f"✓ CDP OK: {url}"
                    else:
                        status = f"CDP HTTP {resp.status}"
                        message = f"⚠ CDP HTTP {resp.status}: {version_url}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                message = f"⚠ CDP chưa sẵn sàng: {exc}"
            self._cdp_check_done.emit(healthy, status, message)

        threading.Thread(target=worker, daemon=True).start()

    def _on_cdp_check_done(self, healthy: bool, status: str, message: str) -> None:
        try:
            self._update_status(status, healthy=healthy)
            if message:
                self._emit(message)
        finally:
            self.btn_check.setEnabled(True)
