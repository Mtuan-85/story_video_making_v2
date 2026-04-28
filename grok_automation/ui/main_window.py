from __future__ import annotations

import os
from pathlib import Path

from loguru import logger
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from grok.browser import BrowserManager
from grok.runner import FlowRunner
from ui.panels import (
    ConnectionPanel,
    GenerationPanel,
    LogPanel,
    RunPanel,
)
from workers.automation_worker import (
    AutomationWorker,
    determine_flow,
    get_target_count,
    validate_before_start,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Grok Automation")
        self.resize(900, 800)

        self.browser = BrowserManager()
        self.worker = AutomationWorker()
        self.runner: FlowRunner | None = None
        self.settings = QSettings("Tuan", "GrokAutomation")

        default_cdp = os.environ.get("CDP_URL", "http://localhost:9222")
        self.output_dir = Path(os.environ.get("OUTPUT_DIR", "./output")).resolve()

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.connection_panel = ConnectionPanel(default_cdp_url=default_cdp)
        self.generation_panel = GenerationPanel()
        self.run_panel = RunPanel()
        self.log_panel = LogPanel()

        root.addWidget(self.connection_panel)
        root.addWidget(self.generation_panel)
        root.addWidget(self.run_panel)
        root.addWidget(self.log_panel, 1)

        self._wire()
        self._restore_state()

    def _wire(self) -> None:
        self.connection_panel.connect_requested.connect(self._on_connect)
        self.connection_panel.disconnect_requested.connect(self._on_disconnect)
        self.connection_panel.refresh_tabs_requested.connect(self._on_refresh_tabs)
        self.connection_panel.tab_selected.connect(self._on_tab_selected)

        self.run_panel.start_clicked.connect(self._on_start)
        self.run_panel.stop_clicked.connect(self._on_stop)

    # ---------- QSettings persist ----------

    def _restore_state(self) -> None:
        gen = self.generation_panel
        s = self.settings
        gen.project_input.setText(s.value("project_name", "", type=str))
        gen.ref_folder_input.setText(s.value("ref_folder", "", type=str))
        try:
            gen.timeout_input.setValue(int(s.value("wait_timeout_s", 60)))
        except (TypeError, ValueError):
            gen.timeout_input.setValue(60)

        type_ = s.value("type", "image", type=str)
        if type_ == "video":
            gen.type_video.setChecked(True)
        else:
            gen.type_image.setChecked(True)

        quality = s.value("quality", "quality", type=str)
        if quality == "speed":
            gen.quality_speed.setChecked(True)
        else:
            gen.quality_quality.setChecked(True)

        aspect = s.value("aspect", "16:9", type=str)
        idx = gen.aspect.findText(aspect)
        if idx >= 0:
            gen.aspect.setCurrentIndex(idx)

        resolution = s.value("resolution", "720p", type=str)
        if resolution == "480p":
            gen.res_480.setChecked(True)
        else:
            gen.res_720.setChecked(True)

        duration = s.value("duration", "6s", type=str)
        if duration == "10s":
            gen.dur_10.setChecked(True)
        else:
            gen.dur_6.setChecked(True)

        pick_mode = s.value("pick_mode", "auto", type=str)
        if pick_mode == "claude":
            gen.pick_claude.setChecked(True)
        else:
            gen.pick_auto.setChecked(True)

        typing_speed = s.value("typing_speed", "fast", type=str)
        if typing_speed == "human":
            gen.speed_human.setChecked(True)
        elif typing_speed == "slow":
            gen.speed_slow.setChecked(True)
        else:
            gen.speed_fast.setChecked(True)

        gen._update_visibility()

        ref = gen.ref_folder_input.text().strip()
        if ref:
            gen._scan_ref_folder(ref)

    def _save_state(self) -> None:
        gen = self.generation_panel
        s = gen.get_settings()
        store = self.settings
        store.setValue("project_name", s["project_name"])
        store.setValue("ref_folder", s["ref_folder"])
        store.setValue("wait_timeout_s", s["wait_timeout_s"])
        store.setValue("type", s["type"])
        store.setValue("quality", s["quality"])
        store.setValue("aspect", s["aspect"])
        store.setValue("resolution", s["resolution"])
        store.setValue("duration", s["duration"])
        store.setValue("pick_mode", s["pick_mode"])
        store.setValue("typing_speed", s["typing_speed"])

    # ---------- Connection ----------

    def _on_connect(self, cdp_url: str) -> None:
        self.connection_panel.set_status(f"đang kết nối tới {cdp_url}...")
        self.worker.run(self._connect_flow(cdp_url))

    async def _connect_flow(self, cdp_url: str) -> None:
        result = await self.browser.connect(cdp_url)
        if not result.get("ok"):
            self.connection_panel.set_status(f"lỗi: {result.get('reason')}")
            self.connection_panel.set_state(connected=False)
            return
        self.connection_panel.set_state(connected=True)
        self.connection_panel.set_status("đã kết nối, đang lấy danh sách tab...")
        tabs = await self.browser.list_tabs(grok_only=True)
        self.connection_panel.populate_tabs(tabs)
        if tabs:
            self.connection_panel.set_status(f"tìm thấy {len(tabs)} tab Grok")
            await self.browser.select_tab(int(tabs[0]["index"]))
        else:
            self.connection_panel.set_status(
                "không có tab grok.com — mở grok.com/imagine trong Chrome rồi bấm Làm mới"
            )

    def _on_disconnect(self) -> None:
        self.worker.run(self._disconnect_flow())

    async def _disconnect_flow(self) -> None:
        await self.browser.disconnect()
        self.connection_panel.set_state(connected=False)
        self.connection_panel.populate_tabs([])
        self.connection_panel.set_status("đã ngắt kết nối")

    def _on_refresh_tabs(self) -> None:
        self.worker.run(self._refresh_flow())

    async def _refresh_flow(self) -> None:
        tabs = await self.browser.list_tabs(grok_only=True)
        self.connection_panel.populate_tabs(tabs)
        self.connection_panel.set_status(f"tìm thấy {len(tabs)} tab Grok")

    def _on_tab_selected(self, page_index: int) -> None:
        self.worker.run(self._select_flow(page_index))

    async def _select_flow(self, page_index: int) -> None:
        result = await self.browser.select_tab(page_index)
        if not result.get("ok"):
            self.connection_panel.set_status(f"chọn tab thất bại: {result.get('reason')}")
            return
        self.connection_panel.set_status(f"đã chọn: {result.get('title')}")

    # ---------- Run ----------

    def _on_start(self) -> None:
        if not self.browser.is_connected or self.browser.page is None:
            self.run_panel.set_status("Chưa kết nối / chưa chọn tab")
            return

        settings = self.generation_panel.get_settings()

        ok, err = validate_before_start(settings)
        if not ok:
            self.run_panel.set_status(f"❌ {err}")
            self.log_panel.append(f"❌ {err}")
            return

        flow_name = determine_flow(settings)
        target_count = get_target_count(settings)

        config = {
            **settings,
            "flow_name": flow_name,
            "target_count": target_count,
        }
        prompts = settings["prompts"]

        self.runner = FlowRunner(
            page=self.browser.page,
            config=config,
            prompts=prompts,
            output_dir=self.output_dir,
            log_cb=self.log_panel.append,
        )
        self.run_panel.set_running(True)
        self.run_panel.set_status(
            f"Đang chạy {flow_name} với {len(prompts)} prompt (target_count={target_count})..."
        )
        self.log_panel.append(
            f"▶ Flow: {flow_name} | target_count={target_count} | "
            f"quality={settings['quality']} | pick={settings['pick_mode']}"
        )
        self.worker.run(self._run_flow(flow_name))

    async def _run_flow(self, flow_key: str) -> None:
        try:
            assert self.runner is not None
            result = await self.runner.run(flow_key)
            if result.get("ok"):
                self.run_panel.set_status("Hoàn tất ✓")
            else:
                self.run_panel.set_status(f"Kết thúc: {result.get('reason')}")
        finally:
            self.run_panel.set_running(False)

    def _on_stop(self) -> None:
        if self.runner:
            self.runner.request_stop()
            self.run_panel.set_status("Đang dừng...")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self._save_state()
        except Exception as e:
            logger.warning(f"Save state failed: {e}")
        try:
            if self.runner:
                self.runner.request_stop()
            if self.browser.is_connected:
                self.worker.run_blocking(self.browser.disconnect())
        except Exception as e:
            logger.warning(f"Cleanup on close failed: {e}")
        super().closeEvent(event)
