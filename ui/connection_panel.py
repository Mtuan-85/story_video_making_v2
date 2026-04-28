"""CDP connection panel — URL input, connect/disconnect, tab picker."""

from __future__ import annotations

import asyncio

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

from engines.grok import GrokConnection

DEFAULT_CDP_URL = "http://localhost:9222"


class ConnectionPanel(QGroupBox):
    """Wraps GrokConnection. UI emits page_ready(page) when a tab is selected.

    The panel runs async work via a coroutine scheduled on the qasync event loop
    (must already be installed by the app entry point).
    """

    page_ready = pyqtSignal(object)
    disconnected = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Kết nối", parent)
        self.connection = GrokConnection()
        self._build_ui()
        self._update_status("Chưa kết nối", connected=False)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("CDP URL:"))
        self.url_edit = QLineEdit(DEFAULT_CDP_URL)
        self.url_edit.setMinimumWidth(220)
        row1.addWidget(self.url_edit)

        self.btn_connect = QPushButton("🔌 Kết nối")
        self.btn_connect.clicked.connect(self._toggle_connect)
        row1.addWidget(self.btn_connect)

        self.status_label = QLabel("●")
        self.status_label.setMinimumWidth(150)
        row1.addWidget(self.status_label)
        row1.addStretch()
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Tab:"))
        self.tab_combo = QComboBox()
        self.tab_combo.setMinimumWidth(380)
        self.tab_combo.setEnabled(False)
        self.tab_combo.currentIndexChanged.connect(self._on_tab_picked)
        row2.addWidget(self.tab_combo)

        self.btn_refresh = QPushButton("↻ Làm mới tabs")
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.clicked.connect(self._refresh_tabs)
        row2.addWidget(self.btn_refresh)
        row2.addStretch()
        outer.addLayout(row2)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def get_url(self) -> str:
        return self.url_edit.text().strip() or DEFAULT_CDP_URL

    def is_connected(self) -> bool:
        return self.btn_refresh.isEnabled()

    def _update_status(self, text: str, connected: bool) -> None:
        color = "#27ae60" if connected else "#c0392b"
        self.status_label.setText(f'<span style="color:{color}">●</span> {text}')
        self.btn_connect.setText("⏏ Ngắt kết nối" if connected else "🔌 Kết nối")
        self.btn_refresh.setEnabled(connected)
        self.tab_combo.setEnabled(connected)

    def _emit(self, msg: str) -> None:
        log.info(msg)
        self.log_message.emit(msg)

    # ------------------------------------------------------------------
    # Async actions (scheduled on qasync loop)
    # ------------------------------------------------------------------

    def _toggle_connect(self) -> None:
        if self.is_connected():
            asyncio.ensure_future(self._do_disconnect())
        else:
            asyncio.ensure_future(self._do_connect())

    async def _do_connect(self) -> None:
        url = self.get_url()
        self.btn_connect.setEnabled(False)
        self._update_status("Đang kết nối...", connected=False)
        try:
            await self.connection.connect(url)
        except Exception as e:
            self._emit(f"❌ Lỗi kết nối: {e}")
            self._update_status("Kết nối thất bại", connected=False)
            self.btn_connect.setEnabled(True)
            return

        self._emit(f"✓ Kết nối CDP {url}")
        self._update_status("Đã kết nối", connected=True)
        self.btn_connect.setEnabled(True)
        await self._refresh_tabs_async()

    async def _do_disconnect(self) -> None:
        self.btn_connect.setEnabled(False)
        try:
            await self.connection.disconnect()
        except Exception as e:
            self._emit(f"⚠ Lỗi ngắt kết nối: {e}")
        self.tab_combo.clear()
        self._update_status("Chưa kết nối", connected=False)
        self.btn_connect.setEnabled(True)
        self.disconnected.emit()
        self._emit("Đã ngắt kết nối")

    def _refresh_tabs(self) -> None:
        asyncio.ensure_future(self._refresh_tabs_async())

    async def _refresh_tabs_async(self) -> None:
        try:
            tabs = await self.connection.list_tabs(grok_only=True)
        except Exception as e:
            self._emit(f"⚠ Liệt kê tab fail: {e}")
            return

        self.tab_combo.blockSignals(True)
        self.tab_combo.clear()
        if not tabs:
            self.tab_combo.addItem("(Không có tab grok.com — mở grok.com/imagine trên Brave)", -1)
        else:
            for t in tabs:
                title = (t.get("title") or "(untitled)")[:60]
                self.tab_combo.addItem(f"#{t['index']} — {title}", t["index"])
        self.tab_combo.blockSignals(False)

        # Auto-select first valid tab.
        # Note: setCurrentIndex(0) is a no-op when the combo is already at 0
        # (which happens after clear() + addItem with blocked signals — Qt
        # auto-sets currentIndex=0 on first addItem). Trigger the tab handler
        # explicitly to guarantee page_ready is emitted.
        if tabs:
            first_tab_idx = self.tab_combo.itemData(0)
            if first_tab_idx is not None and first_tab_idx >= 0:
                asyncio.ensure_future(self._select_tab_async(int(first_tab_idx)))

    def _on_tab_picked(self, combo_idx: int) -> None:
        tab_idx = self.tab_combo.itemData(combo_idx)
        if tab_idx is None or tab_idx < 0:
            return
        asyncio.ensure_future(self._select_tab_async(int(tab_idx)))

    async def _select_tab_async(self, tab_idx: int) -> None:
        try:
            info = await self.connection.select_tab(tab_idx)
        except Exception as e:
            self._emit(f"⚠ Chọn tab fail: {e}")
            return
        self._emit(f"✓ Tab: {info.get('title')}")
        if self.connection.page is not None:
            self.page_ready.emit(self.connection.page)
