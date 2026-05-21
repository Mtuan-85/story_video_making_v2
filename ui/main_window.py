"""MainWindow — wires connection panel, project loader, scene list, log panel.

UI labels Vietnamese; control flow English. Worker signals update SceneRow
state in the main thread.
"""

from __future__ import annotations

from datetime import datetime
import sys
from pathlib import Path

from loguru import logger as log
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.thumbnail import regenerate_thumbnail
from core.project import Project
from runtime.estimator import Estimator
from ui.connection_panel import ConnectionPanel
from ui.refs_panel import RefImagesPanel
from ui.dialogs.preview_dialog import PreviewDialog
from ui.dialogs.voice_align_review import VoiceAlignReviewDialog
from ui.scene_list import SceneList
from workers._async_thread import AsyncQThread
from workers.export_worker import ExportKdenliveWorker
from workers.render_worker import RenderWorker
from workers.voice_align_worker import VoiceAlignWorker
from workers.process_launcher import GenerateProcess
from workers.slideshow_worker import SlideshowWorker, is_slideshow_eligible
from workers.task_contract import CdpConfig, GenerateTask, TaskOptions, WorkerEvent


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Story Video Maker")
        self.resize(1400, 850)

        self.project: Project | None = None
        self.estimator = Estimator()
        self._generate_proc: GenerateProcess | None = None
        self._generate_active_scene_ids: set[str] = set()
        self._single_video_workers: dict[str, AsyncQThread] = {}
        self._voice_align_worker: VoiceAlignWorker | None = None
        self._render_worker: RenderWorker | None = None
        self._export_worker: ExportKdenliveWorker | None = None
        self._active_workers: list = []

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Worker registry (for Stop All)
    # ------------------------------------------------------------------

    def _register_worker(self, worker) -> None:
        if worker is None or worker in self._active_workers:
            return
        self._active_workers.append(worker)
        if hasattr(worker, "finished"):
            worker.finished.connect(lambda w=worker: self._unregister_worker(w))

    def _unregister_worker(self, worker) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # Connection panel
        self.connection_panel = ConnectionPanel()
        outer.addWidget(self.connection_panel)

        # Project header (full-width — RefImagesPanel now lives next to Log)
        self.project_box = QGroupBox("Dự án")
        proj_layout = QHBoxLayout(self.project_box)
        self.btn_load = QPushButton("📂 Mở scenes.json")
        self.btn_load.clicked.connect(self._load_project)
        proj_layout.addWidget(self.btn_load)

        self.project_label = QLabel("(Chưa load dự án)")
        self.project_label.setStyleSheet("color:#666")
        proj_layout.addWidget(self.project_label, 1)
        outer.addWidget(self.project_box)

        # Scene list + actions
        self.scene_box = QGroupBox("Scenes")
        scene_layout = QVBoxLayout(self.scene_box)

        action_row = QHBoxLayout()
        self.btn_batch_image = QPushButton("➕ Batch ảnh")
        self.btn_batch_image.clicked.connect(self._start_batch_image)
        self.btn_batch_image.setEnabled(False)
        action_row.addWidget(self.btn_batch_image)

        self.btn_batch_video = QPushButton("🎞 Batch video")
        self.btn_batch_video.clicked.connect(self._start_batch_video)
        self.btn_batch_video.setEnabled(False)
        action_row.addWidget(self.btn_batch_video)

        self.btn_batch_edit = QPushButton("🛠 Batch edit")
        self.btn_batch_edit.clicked.connect(self._start_batch_edit)
        self.btn_batch_edit.setEnabled(False)
        action_row.addWidget(self.btn_batch_edit)

        self.btn_stop = QPushButton("■ Dừng")
        self.btn_stop.clicked.connect(self._stop_batch)
        self.btn_stop.setEnabled(False)
        action_row.addWidget(self.btn_stop)

        self.btn_stop_all = QPushButton("🛑 Stop All")
        self.btn_stop_all.setToolTip("Dừng tất cả workers đang chạy")
        self.btn_stop_all.setStyleSheet(
            "QPushButton { background-color: #c62828; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #b71c1c; }"
        )
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        action_row.addWidget(self.btn_stop_all)

        action_row.addSpacing(12)
        self.btn_select_all = QPushButton("☑ All")
        self.btn_select_all.setToolTip("Chọn tất cả scenes cho batch")
        self.btn_select_all.clicked.connect(self._select_all_scenes)
        self.btn_select_all.setEnabled(False)
        action_row.addWidget(self.btn_select_all)

        self.btn_clear_selection = QPushButton("☐ Clear")
        self.btn_clear_selection.setToolTip("Bỏ chọn tất cả scenes")
        self.btn_clear_selection.clicked.connect(self._clear_scene_selection)
        self.btn_clear_selection.setEnabled(False)
        action_row.addWidget(self.btn_clear_selection)

        self.btn_reload = QPushButton("🔄 Reload")
        self.btn_reload.setToolTip(
            "Re-read scenes_edited.json + scan sources/ (auto-pattern match)"
        )
        self.btn_reload.clicked.connect(self._on_reload_project)
        self.btn_reload.setEnabled(False)
        action_row.addWidget(self.btn_reload)

        self.btn_reset_design = QPushButton("↶ Reset to design")
        self.btn_reset_design.setToolTip(
            "Restore scenes from scenes.json (lose all edits in scenes_edited.json)"
        )
        self.btn_reset_design.clicked.connect(self._on_reset_to_design)
        self.btn_reset_design.setEnabled(False)
        action_row.addWidget(self.btn_reset_design)

        self.btn_render = QPushButton("🎬 Render final")
        self.btn_render.clicked.connect(self._start_render)
        self.btn_render.setEnabled(False)
        action_row.addWidget(self.btn_render)

        self.btn_export_kdenlive = QPushButton("📤 Export Kdenlive XML")
        self.btn_export_kdenlive.clicked.connect(self._on_export_kdenlive)
        self.btn_export_kdenlive.setEnabled(False)
        action_row.addWidget(self.btn_export_kdenlive)

        action_row.addSpacing(12)
        self.selection_label = QLabel("Đã chọn: 0/0")
        self.selection_label.setStyleSheet("color:#666")
        action_row.addWidget(self.selection_label)

        action_row.addStretch()
        self.progress_label = QLabel("0/0")
        action_row.addWidget(self.progress_label)
        scene_layout.addLayout(action_row)

        self.scene_list = SceneList()
        scene_layout.addWidget(self.scene_list, 1)
        outer.addWidget(self.scene_box, 1)

        # Log + Reference Images side-by-side
        log_row = QHBoxLayout()

        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        log_layout.addWidget(self.log_view)

        log_btns = QHBoxLayout()
        btn_clear_log = QPushButton("🗑 Xóa log")
        btn_clear_log.clicked.connect(self.log_view.clear)
        log_btns.addStretch()
        log_btns.addWidget(btn_clear_log)
        log_layout.addLayout(log_btns)

        log_row.addWidget(log_box, 7)

        self.refs_panel = RefImagesPanel()
        self.refs_panel.refs_changed.connect(self._on_refs_changed)
        log_row.addWidget(self.refs_panel, 3)

        outer.addLayout(log_row)

        # Loguru sink → log panel
        log.add(self._sink, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    def _wire_signals(self) -> None:
        self.connection_panel.log_message.connect(self._append_log)
        self.connection_panel.page_ready.connect(self._on_page_ready)
        self.connection_panel.disconnected.connect(self._on_disconnected)

        self.scene_list.edit_clicked.connect(self._show_preview_dialog)
        self.scene_list.visual_type_changed.connect(self._on_visual_type_changed)
        self.scene_list.effect_changed.connect(self._on_effect_changed)
        self.scene_list.batch_selection_changed.connect(self._on_batch_selection_changed)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _sink(self, message) -> None:
        try:
            text = message.record["message"]
            self.log_view.append(f"{message.record['time'].strftime('%H:%M:%S')}  {text}")
        except Exception:
            pass

    def _append_log(self, msg: str) -> None:
        self.log_view.append(msg)

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    def _load_project(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Chọn file project (.json)", "", "JSON Files (*.json)"
        )
        if not path_str:
            return
        scenes_path = Path(path_str)
        try:
            self.project = Project.load(scenes_path)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi load dự án", str(e))
            self._append_log(f"❌ Load dự án fail: {e}")
            return

        meta = self.project.scenes_json.meta
        self.project_label.setText(
            f"<b>{meta.title}</b> — {meta.aspect_ratio} / {meta.language} — "
            f"{len(self.project.scenes)} scenes — <span style='color:#666'>{self.project.paths.root}</span>"
        )
        self.scene_list.bind_project(self.project)  # emits batch_selection_changed
        self.btn_reload.setEnabled(True)
        self.btn_reset_design.setEnabled(True)
        self.btn_render.setEnabled(self.project.voice_mapping is not None)
        self.btn_export_kdenlive.setEnabled(True)

        self.refs_panel.set_state(
            paths=[str(p) for p in self.project.get_image_refs()],
            use_refs=self.project.get_use_refs_for_image(),
        )
        self.refs_panel.setEnabled(True)

        self._append_log(f"✓ Đã load dự án: {meta.title}")

    def _on_refs_changed(self, paths: list, use_refs: bool) -> None:
        if self.project is None:
            return
        self.project.set_image_refs([str(p) for p in paths])
        self.project.set_use_refs_for_image(bool(use_refs))

    # ------------------------------------------------------------------
    # Connection callbacks
    # ------------------------------------------------------------------

    def _on_page_ready(self, _page) -> None:
        self._append_log("ℹ Browser pages are owned by worker processes.")
        self._refresh_batch_buttons()

    def _on_disconnected(self) -> None:
        self._refresh_batch_buttons()

    def _on_browser_disconnected(self) -> None:
        self._refresh_batch_buttons()
        self._append_log("ℹ Worker reported browser/CDP disconnect.")

    def _refresh_batch_buttons(self) -> None:
        self._on_batch_selection_changed(
            len(self.scene_list.selected_scene_ids()), len(self.scene_list.rows)
        )

    # ------------------------------------------------------------------
    # Batch image
    # ------------------------------------------------------------------

    def _build_generate_task(
        self,
        task_type: str,
        scene_ids: list[str],
        fast_mode: bool = False,
    ) -> GenerateTask:
        if self.project is None:
            raise RuntimeError("Project is not loaded")

        refs = [str(p) for p in self.project.get_image_refs()]
        task_id = f"{task_type}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        return GenerateTask(
            task_id=task_id,
            project_file=str(self.project.paths.scenes_original),
            project_root=str(self.project.paths.root),
            task_type=task_type,
            scene_ids=scene_ids,
            provider=self.connection_panel.selected_provider(),
            model=self.connection_panel.selected_model(),
            cdp=CdpConfig(
                url=self.connection_panel.cdp_url(),
                base_url="https://grok.com/imagine",
            ),
            options=TaskOptions(
                fast_mode=fast_mode,
                use_refs_for_image=self.project.get_use_refs_for_image(),
                image_refs=refs,
            ),
        )

    def _start_generate_process(self, task: GenerateTask) -> None:
        if self.project is None:
            return
        if self._generate_proc is not None and self._generate_proc.is_running():
            QMessageBox.information(self, "Đang chạy", "Image generation đang chạy.")
            return
        other_running = any(self._is_worker_running(w) for w in self._active_workers)
        if other_running:
            QMessageBox.information(
                self,
                "Đang chạy",
                "Đợi worker hiện tại xong trước khi bắt đầu image generation.",
            )
            return

        task_path = self.project.paths.temp_dir / "tasks" / f"{task.task_id}.json"
        proc = GenerateProcess(task, task_path, parent=self)
        proc.log_line.connect(self._append_log)
        proc.event.connect(self._on_generate_event)
        proc.finished.connect(self._on_generate_finished)
        self._generate_proc = proc
        self._register_worker(proc)
        self.btn_stop.setEnabled(True)
        self._append_log(f"▶ Bắt đầu {task.task_type}: {len(task.scene_ids)} scene(s)")
        proc.start()
        self._refresh_batch_buttons()

    def _on_generate_event(self, event: WorkerEvent) -> None:
        if self.project is None:
            return

        payload = event.payload
        scene_id = payload.get("scene_id")
        asset = payload.get("asset", "image")
        if asset != "image":
            return

        if event.type == "scene_started" and isinstance(scene_id, str):
            self._generate_active_scene_ids.add(scene_id)
            self.project.update_scene_state(
                scene_id,
                "image",
                {"status": "generating", "fail_reason": None},
            )
            self.scene_list.refresh_row(scene_id)
            return

        if event.type == "scene_done" and isinstance(scene_id, str):
            raw_path = payload.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                self._mark_generate_event_failed(scene_id, "worker returned empty image path")
                return
            path = raw_path.strip()
            visual_path = Path(path)
            if not visual_path.is_absolute():
                visual_path = self.project.paths.root / visual_path
            if not visual_path.exists():
                self._mark_generate_event_failed(
                    scene_id, f"worker image path does not exist: {path}"
                )
                return
            self.project.update_scene_state(
                scene_id,
                "image",
                {
                    "status": "ready",
                    "path": path,
                    "fail_reason": None,
                    "last_gen_at": datetime.now().isoformat(timespec="seconds"),
                },
            )
            self.project.clear_warnings(scene_id, code="grok_no_image")
            regenerate_thumbnail(
                project_root=self.project.paths.root,
                scene_id=scene_id,
                visual_path=visual_path,
                visual_kind="image",
            )
            self._generate_active_scene_ids.discard(scene_id)
            self.scene_list.refresh_row(scene_id)
            return

        if event.type == "scene_failed" and isinstance(scene_id, str):
            reason = str(payload.get("reason") or "unknown")
            self._mark_generate_event_failed(scene_id, reason)
            return

        if event.type == "task_start":
            self._append_log(f"▶ Task started: {payload}")
        elif event.type == "task_done":
            self._on_progress(int(payload.get("success", 0)), int(payload.get("total", 0)))
            self._append_log(f"✓ Task done: {payload}")
        elif event.type == "task_failed":
            self._append_log(f"❌ Task failed: {payload}")

    def _on_generate_finished(self, exit_code: int) -> None:
        proc = self._generate_proc
        self._generate_proc = None
        if proc is not None:
            self._unregister_worker(proc)
            proc.deleteLater()
        if self._generate_active_scene_ids:
            reason = f"worker exited before scene_done (exit_code={exit_code})"
            for scene_id in list(self._generate_active_scene_ids):
                self._mark_generate_event_failed(scene_id, reason)
            self._generate_active_scene_ids.clear()
        self._refresh_stop_button()
        self._refresh_batch_buttons()
        self._append_log(f"■ Image generation process exited: {exit_code}")

    def _mark_generate_event_failed(self, scene_id: str, reason: str) -> None:
        if self.project is None:
            return
        self.project.update_scene_state(
            scene_id,
            "image",
            {"status": "failed", "fail_reason": reason},
        )
        self.project.add_warning(scene_id, "grok_no_image", reason)
        self._generate_active_scene_ids.discard(scene_id)
        self.scene_list.refresh_row(scene_id)
        self._append_log(f"❌ {scene_id}: {reason}")

    def _refresh_stop_button(self) -> None:
        self.btn_stop.setEnabled(any(self._is_worker_running(w) for w in self._active_workers))

    def _start_batch_image(self) -> None:
        if self.project is None:
            return

        # Count scenes that actually need work (filter by batch selection)
        selected_ids = set(self.scene_list.selected_scene_ids())
        pending = [
            s for s in self.project.scenes
            if s.id in selected_ids
            and self.project.get_scene_state(s.id)["image"]["status"] != "ready"
        ]
        if not pending:
            QMessageBox.information(
                self, "Không có gì để làm",
                "Các scene đã chọn đều có ảnh rồi (hoặc chưa chọn scene nào). "
                "Dùng nút 🔄 từng scene để re-gen.",
            )
            return

        info = self.estimator.estimate_batch("gen_image", n=len(pending))
        confirm = QMessageBox.question(
            self,
            "Xác nhận batch ảnh",
            f"Sắp gen {len(pending)} ảnh.\n\n"
            f"Ước tính: {info['formatted_avg']}\n{info['formatted_p90']}\n\n"
            f"Bắt đầu?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        task = self._build_generate_task("batch_image", [s.id for s in pending])
        self._start_generate_process(task)

    def _stop_batch(self) -> None:
        if self._generate_proc is not None and self._generate_proc.is_running():
            self._generate_proc.kill()
            self._append_log("⏸ Đang dừng image generation...")
        if self._render_worker is not None and self._render_worker.isRunning():
            self._render_worker.request_stop()
            self._append_log("⏸ Đang dừng render...")

    def _on_stop_all(self) -> None:
        active = [w for w in self._active_workers if self._is_worker_running(w)]
        if not active:
            QMessageBox.information(
                self, "Stop All", "Không có worker nào đang chạy."
            )
            return

        n = len(active)
        reply = QMessageBox.question(
            self,
            "Stop All?",
            f"Dừng tất cả {n} worker đang chạy?\n\n"
            "Lưu ý: Một số tác vụ có thể đã hoàn thành 1 phần (vd download dở dang).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        log.info(f"Stop All: stopping {n} workers")
        for worker in list(active):
            try:
                if hasattr(worker, "request_stop"):
                    worker.request_stop()
                elif hasattr(worker, "stop"):
                    worker.stop()
                elif hasattr(worker, "kill"):
                    worker.kill()
                log.info(f"Sent stop to: {worker.__class__.__name__}")
            except Exception as e:
                log.error(f"Failed to stop {worker.__class__.__name__}: {e}")
        self._append_log(f"🛑 Stop All: signaled {n} worker(s) to stop")

    @staticmethod
    def _is_worker_running(worker) -> bool:
        try:
            if hasattr(worker, "is_running"):
                return bool(worker.is_running())
            if hasattr(worker, "isRunning"):
                return bool(worker.isRunning())
        except Exception:
            return False
        return True

    def _on_scene_started(self, scene_id: str) -> None:
        self.scene_list.refresh_row(scene_id)

    def _on_scene_finished(self, scene_id: str, _state: dict) -> None:
        self.scene_list.refresh_row(scene_id)

    def _on_scene_failed(self, scene_id: str, _reason: str) -> None:
        self.scene_list.refresh_row(scene_id)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress_label.setText(f"{done}/{total}")

    def _on_batch_done(self, success: int, total: int) -> None:
        self._refresh_stop_button()
        self._refresh_batch_buttons()
        self._append_log(f"✓ Batch ảnh xong: {success}/{total}")

    # ------------------------------------------------------------------
    # Batch video
    # ------------------------------------------------------------------

    def _start_batch_video(self) -> None:
        if self.project is None:
            return
        QMessageBox.information(
            self,
            "Batch video deferred",
            "Batch Grok video generation is deferred until the video worker "
            "is moved to the process launcher. Use Batch Edit for slideshow/edit tools.",
        )

    def _start_batch_edit(self) -> None:
        if self.project is None:
            return
        if any(self._is_worker_running(w) for w in self._active_workers):
            QMessageBox.information(
                self,
                "Đang chạy",
                "Đợi worker hiện tại xong trước khi bắt đầu batch edit.",
            )
            return

        selected_ids = set(self.scene_list.selected_scene_ids())
        eligible: list[str] = []
        skipped: list[tuple[str, str]] = []
        for scene in self.project.scenes:
            if scene.id not in selected_ids:
                continue
            if scene.visual_type != "slideshow":
                skipped.append((scene.id, f"visual_type={scene.visual_type}, không phải slideshow"))
                continue
            ok, reason = is_slideshow_eligible(self.project, scene.id)
            if ok:
                eligible.append(scene.id)
            else:
                skipped.append((scene.id, reason))

        if not eligible:
            msg = "Không có scene nào đủ điều kiện Batch Edit (slideshow)."
            if skipped:
                msg += "\n\nLý do bỏ qua:\n" + "\n".join(
                    f"  • {sid}: {reason}" for sid, reason in skipped[:8]
                )
            QMessageBox.information(self, "Không có gì để làm", msg)
            return

        if skipped:
            self._append_log(
                "Batch Edit sẽ bỏ qua: "
                + "; ".join(f"{sid} ({reason})" for sid, reason in skipped[:8])
            )

        self._start_next_edit(eligible)

    def _start_next_edit(self, scene_ids: list[str]) -> None:
        if not scene_ids:
            self._append_log("✓ Batch edit xong")
            self._refresh_batch_buttons()
            return
        scene_id = scene_ids[0]
        rest = scene_ids[1:]
        self._start_single_edit_worker(
            scene_id,
            on_finished=lambda remaining=rest: self._start_next_edit(remaining),
        )

    def _on_batch_video_done(self, success: int, total: int) -> None:
        self._refresh_stop_button()
        self._refresh_batch_buttons()
        self._append_log(f"✓ Batch video xong: {success}/{total}")

    # ------------------------------------------------------------------
    # User-decision popup after retry exhausts
    # ------------------------------------------------------------------

    def _ask_user_decision(self, worker, scene_id: str, attempts: int) -> None:
        """Modal popup → set worker.set_user_decision('retry'|'cancel').

        Retry → chạy thêm 1 vòng (3 attempts). Fail tiếp → batch dừng hẳn.
        Cancel → batch dừng ngay.
        """
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(f"Scene {scene_id} fail")
        msg.setText(
            f"Scene {scene_id} fail {attempts} lần liên tiếp.\n\n"
            "Retry → thử lại thêm 1 vòng (3 attempts). Nếu vẫn fail, batch sẽ dừng hẳn.\n"
            "Cancel → dừng cả batch ngay bây giờ."
        )
        btn_retry = msg.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        decision = "retry" if msg.clickedButton() == btn_retry else "cancel"
        worker.set_user_decision(decision)

    # ------------------------------------------------------------------
    # Single re-gen
    # ------------------------------------------------------------------

    def _regen_one(self, scene_id: str, fast_mode: bool = False) -> None:
        if self.project is None:
            QMessageBox.information(self, "Chưa sẵn sàng", "Load dự án trước")
            return
        if self._generate_proc is not None and self._generate_proc.is_running():
            QMessageBox.information(self, "Đang chạy", "Image generation đang chạy.")
            return
        task = self._build_generate_task("single_image", [scene_id], fast_mode=fast_mode)
        self._start_generate_process(task)

    def _regen_one_video(self, scene_id: str, fast_mode: bool = False) -> None:
        """Dispatch a one-scene provider video re-gen by visual_type.

        Video         → deferred until video process worker refactor
        Image/slideshow → not provider video
        """
        if self.project is None:
            QMessageBox.information(self, "Chưa sẵn sàng", "Load dự án trước")
            return
        if any(self._is_worker_running(w) for w in self._active_workers):
            QMessageBox.information(
                self,
                "Đang chạy",
                "Đợi worker hiện tại xong trước khi bắt đầu video.",
            )
            return
        if scene_id in self._single_video_workers and self._single_video_workers[scene_id].isRunning():
            return

        scene = self.project.scene(scene_id)
        vtype = scene.visual_type

        if vtype == "Video":
            QMessageBox.information(
                self,
                "Grok video deferred",
                "Grok video generation is deferred until the video worker "
                "is moved to the process launcher.",
            )
            return

        QMessageBox.information(
            self, "Không phải provider video",
            f"Scene {scene_id} có visual_type={vtype}. "
            "Dùng Single Edit để chạy slideshow/edit tool.",
        )

    def _regen_one_edit(self, scene_id: str, _fast_mode: bool = False) -> None:
        if self.project is None:
            QMessageBox.information(self, "Chưa sẵn sàng", "Load dự án trước")
            return
        if any(self._is_worker_running(w) for w in self._active_workers):
            QMessageBox.information(
                self,
                "Đang chạy",
                "Đợi worker hiện tại xong trước khi bắt đầu edit.",
            )
            return
        scene = self.project.scene(scene_id)
        if scene.visual_type != "slideshow":
            QMessageBox.information(
                self,
                "Không phải edit tool",
                f"Scene {scene_id} có visual_type={scene.visual_type}. "
                "Đổi visual_type sang slideshow để chạy Single Edit.",
            )
            return
        ok, reason = is_slideshow_eligible(self.project, scene_id)
        if not ok:
            QMessageBox.warning(self, f"Không đủ điều kiện — {scene_id}", reason)
            return
        self._start_single_edit_worker(scene_id)

    def _start_single_edit_worker(self, scene_id: str, on_finished=None) -> None:
        if self.project is None:
            return
        if scene_id in self._single_video_workers and self._single_video_workers[scene_id].isRunning():
            return

        worker = SlideshowWorker(self.project, scene_id, estimator=self.estimator)
        worker.scene_started.connect(self._on_scene_started)
        worker.scene_finished.connect(self._on_scene_finished)
        worker.scene_failed.connect(self._on_scene_failed)
        worker.log_message.connect(self._append_log)
        worker.finished.connect(lambda sid=scene_id: self._cleanup_single_video(sid))
        if on_finished is not None:
            worker.finished.connect(on_finished)
        self._single_video_workers[scene_id] = worker
        worker.start()
        self._register_worker(worker)

    def _cleanup_single_video(self, scene_id: str) -> None:
        w = self._single_video_workers.pop(scene_id, None)
        if w is not None:
            w.deleteLater()

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _on_batch_selection_changed(self, selected: int, total: int) -> None:
        self.selection_label.setText(f"Đã chọn: {selected}/{total}")
        image_running = self._generate_proc is not None and self._generate_proc.is_running()
        other_running = any(
            self._is_worker_running(w)
            for w in self._active_workers
            if w is not self._generate_proc
        )
        self.btn_batch_image.setEnabled(
            self.project is not None and selected > 0 and not image_running and not other_running
        )
        self.btn_batch_video.setEnabled(
            self.project is not None and selected > 0 and not image_running and not other_running
        )
        self.btn_batch_edit.setEnabled(
            self.project is not None and selected > 0 and not image_running and not other_running
        )
        self.btn_select_all.setEnabled(self.project is not None and total > 0)
        self.btn_clear_selection.setEnabled(self.project is not None and total > 0)

    def _select_all_scenes(self) -> None:
        self.scene_list.select_all()

    def _clear_scene_selection(self) -> None:
        self.scene_list.clear_selection()

    def _on_visual_type_changed(self, scene_id: str, new_value: str) -> None:
        if self.project is None:
            return
        try:
            self.project.update_scene_field(scene_id, "visual_type", new_value)
            self._append_log(f"{scene_id} visual_type → {new_value}")
            self.scene_list.refresh_row(scene_id)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu", f"Cập nhật visual_type fail: {e}")

    def _on_effect_changed(self, scene_id: str, new_value: str) -> None:
        if self.project is None:
            return
        try:
            self.project.update_scene_field(scene_id, "effect", new_value)
            self._append_log(f"{scene_id} effect → {new_value}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu", f"Cập nhật effect fail: {e}")

    def _resolve_asset_path(self, rel_or_abs: str | None) -> Path | None:
        if not rel_or_abs or self.project is None:
            return None
        p = Path(rel_or_abs)
        if not p.is_absolute():
            p = self.project.paths.root / p
        return p if p.exists() else p  # caller decides on missing-file UX

    def _show_preview_dialog(self, scene_id: str) -> None:
        """Unified preview + edit. Entry point for thumbnail, 🖼/🎬, and ✏ clicks.

        Save → atomic write scenes_edited.json.
        Gen Image / Gen Animation → save first, then dispatch the right worker.
        """
        if self.project is None:
            return
        scene = self.project.scene(scene_id)
        scene_state = self.project.get_scene_state(scene_id)
        dlg = PreviewDialog(
            scene=scene,
            scene_state=scene_state,
            project_root=self.project.paths.root,
            parent=self,
        )
        dlg.save_requested.connect(self._on_preview_save)
        dlg.gen_image_requested.connect(self._regen_one)
        dlg.gen_animation_requested.connect(self._regen_one_video)
        dlg.gen_edit_requested.connect(self._regen_one_edit)
        dlg.exec()

    def _on_preview_save(self, scene_id: str, updates: dict) -> None:
        if self.project is None:
            return
        try:
            self.project.update_scene_fields(scene_id, updates)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu", f"Cập nhật scene fail: {e}")
            return
        self.scene_list.refresh_row(scene_id)
        self._append_log(f"✓ Đã lưu prompts cho {scene_id}")

    # ------------------------------------------------------------------
    # Voice alignment (Plan D — auto-trigger, no wizard)
    # ------------------------------------------------------------------

    _VOICE_EXTS = (".mp3", ".wav", ".m4a", ".flac")

    def _scan_voice_dir(self, voice_dir: Path) -> list[Path]:
        files: list[Path] = []
        for ext in self._VOICE_EXTS:
            files.extend(voice_dir.glob(f"*{ext}"))
        return sorted(files, key=lambda p: p.name.lower())

    def _on_process_voice(self) -> None:
        """Auto-align voice/ folder against scenes (Plan D, no wizard)."""
        if self.project is None:
            return
        if self._voice_align_worker is not None and self._voice_align_worker.isRunning():
            QMessageBox.information(self, "Đang chạy", "Alignment đang chạy, đợi xong rồi thử lại.")
            return

        voice_dir = self.project.paths.voice_dir
        voice_files = self._scan_voice_dir(voice_dir)
        if not voice_files:
            QMessageBox.warning(
                self,
                "Không có voice",
                f"Folder voice/ trống. Bỏ file mp3/wav vào:\n{voice_dir}",
            )
            return

        scenes = [
            {
                "id": s.id,
                "story_en": s.story_en,
                "story_vi": s.story_vi,
                "duration": s.duration,
            }
            for s in self.project.scenes
        ]
        language = self.project.scenes_json.meta.language
        self._append_log(
            f"▶ Plan D align: {len(voice_files)} voice file(s), {len(scenes)} scene(s), "
            f"lang={language}"
        )

        worker = VoiceAlignWorker(
            voice_files=voice_files,
            scene_assignments={},  # Plan D auto-matches; legacy field
            scenes=scenes,
            work_dir=self.project.paths.temp_dir,
            project_root=self.project.paths.root,
            silent_scenes=[],  # Plan D detects silent via low score
            whisper_model="base",
            language=language,
        )
        worker.log_message.connect(self._append_log)
        worker.failed.connect(
            lambda fn, msg: self._append_log(f"❌ {fn}: {msg}")
        )
        worker.all_done.connect(self._on_voice_align_done)
        worker.finished.connect(self._cleanup_voice_align)
        self._voice_align_worker = worker
        worker.start()
        self._register_worker(worker)

    def _on_reset_to_design(self) -> None:
        if self.project is None:
            return
        reply = QMessageBox.question(
            self,
            "Reset to design?",
            "Tất cả edits trong scenes_edited.json sẽ bị mất. "
            "Restore từ scenes.json gốc?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.project.reset_to_design()
        except Exception as e:
            QMessageBox.critical(self, "Reset failed", str(e))
            return
        self.scene_list.bind_project(self.project)
        self._append_log("✓ Reset: scenes_edited.json restored from scenes.json")

    def _on_reload_project(self) -> None:
        if self.project is None:
            QMessageBox.information(self, "Reload", "Chưa load project nào.")
            return
        try:
            summary = self.project.reload()
        except Exception as e:
            log.error(f"Reload failed: {e}")
            QMessageBox.critical(self, "Reload failed", str(e))
            return

        self.scene_list.refresh_all()
        self._append_log(
            f"🔄 Reload: {summary['images_found']}/{summary['scenes_count']} ảnh, "
            f"{summary['videos_found']} video, "
            f"{len(summary['missing'])} missing, "
            f"{len(summary['orphans'])} orphan"
        )
        self._show_reload_summary(summary)

    def _show_reload_summary(self, summary: dict) -> None:
        scenes_count = summary["scenes_count"]
        images_found = summary["images_found"]
        videos_found = summary["videos_found"]
        missing = summary["missing"]
        orphans = summary["orphans"]

        lines = [
            "<b>Reload xong</b>",
            "",
            f"📋 Scenes: {scenes_count}",
            f"🖼 Images found: {images_found}/{scenes_count}",
            f"🎞 Videos found: {videos_found} (chỉ scenes cần video)",
        ]

        if missing:
            lines.append("")
            lines.append(f"<b>⚠ Missing files ({len(missing)} scenes):</b>")
            for item in missing[:10]:
                miss_types = ", ".join(item["missing"])
                lines.append(f"  • {item['scene_id']}: thiếu {miss_types}")
            if len(missing) > 10:
                lines.append(f"  ... và {len(missing) - 10} scenes khác")
            lines.append("")
            lines.append(
                "<i>Patterns chấp nhận: pic{N}.jpg, scene_{N}.jpg, "
                "pic{N:02d}.jpg, scene_{N:02d}.jpg (.jpg/.jpeg/.png/.webp)</i>"
            )

        if orphans:
            lines.append("")
            lines.append(f"<b>📂 Orphan files ({len(orphans)}):</b>")
            lines.append("<i>Files trong sources/ không match scene nào:</i>")
            for name in orphans[:5]:
                lines.append(f"  • {name}")
            if len(orphans) > 5:
                lines.append(f"  ... và {len(orphans) - 5} files khác")

        if not missing and not orphans:
            lines.append("")
            lines.append("<b style='color:#2e7d32'>✓ All sources matched cleanly</b>")

        box = QMessageBox(self)
        box.setWindowTitle("Reload — Summary")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText("<br>".join(lines))
        box.setIcon(QMessageBox.Icon.Warning if missing else QMessageBox.Icon.Information)
        box.exec()

    def _on_voice_align_done(self, mapping) -> None:
        from core.voice_mapping import VoiceMapping  # local import to keep top tidy
        if not isinstance(mapping, VoiceMapping):
            self._append_log("⚠ alignment trả về dữ liệu không hợp lệ")
            return
        if self.project is None:
            return
        self.project.save_voice_mapping(mapping)
        self._append_log(
            f"✓ Alignment xong: {len(mapping.voice_files)} file, "
            f"silent={len(mapping.silent_scenes)} scenes — đã lưu voice_mapping.json"
        )
        scenes_data = [
            {
                "id": s.id,
                "story_en": s.story_en,
                "story_vi": s.story_vi,
                "duration": s.duration,
            }
            for s in self.project.scenes
        ]
        whisper_words: list = []
        whisper_words_path = self.project.paths.root / "whisper_words.json"
        if whisper_words_path.exists():
            try:
                import json as _json
                whisper_words = _json.loads(whisper_words_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"could not load whisper_words.json: {e}")
        dlg = VoiceAlignReviewDialog(
            voice_mapping=mapping,
            scenes_data=scenes_data,
            whisper_words=whisper_words,
            parent=self,
        )
        dlg.save_requested.connect(self._on_voice_mapping_saved)
        result = dlg.exec()
        # Re-align all = result code 2 (set by dialog button).
        if result == 2:
            self._on_process_voice()

    def _on_voice_mapping_saved(self, mapping) -> None:
        from core.voice_mapping import VoiceMapping
        if self.project is None:
            return
        if isinstance(mapping, dict):
            try:
                mapping = VoiceMapping.model_validate(mapping)
            except Exception as e:
                self._append_log(f"❌ voice_mapping schema invalid: {e}")
                return
        self.project.save_voice_mapping(mapping)
        self._append_log("✓ Đã lưu chỉnh sửa timestamps")
        self.btn_render.setEnabled(True)

    def _cleanup_voice_align(self) -> None:
        worker = self._voice_align_worker
        if worker is not None:
            worker.deleteLater()
        self._voice_align_worker = None
        if self.project is not None and self.project.voice_mapping is not None:
            self.btn_render.setEnabled(True)

    # ------------------------------------------------------------------
    # Render final (Sprint 2 Phase 2B)
    # ------------------------------------------------------------------

    def _start_render(self) -> None:
        if self.project is None:
            return
        if self.project.voice_mapping is None:
            QMessageBox.warning(
                self, "Chưa có voice_mapping",
                "Import voice và alignment trước khi render final.",
            )
            return
        if self._render_worker is not None and self._render_worker.isRunning():
            return

        bgm_dir = self.project.paths.bgm_dir
        worker = RenderWorker(
            project=self.project,
            voice_mapping=self.project.voice_mapping,
            bgm_dir=bgm_dir if bgm_dir.exists() else None,
        )
        worker.log_message.connect(self._append_log)
        worker.scene_failed.connect(
            lambda sid, r: self._append_log(f"❌ {sid}: {r}")
        )
        worker.progress.connect(
            lambda i, n: self.progress_label.setText(f"{i}/{n}")
        )
        worker.finished_ok.connect(self._on_render_ok)
        worker.finished_fail.connect(self._on_render_fail)
        worker.finished.connect(self._cleanup_render)
        self._render_worker = worker
        self.btn_render.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._append_log("▶ Bắt đầu render final...")
        worker.start()
        self._register_worker(worker)

    def _on_render_ok(self, path: str) -> None:
        self._append_log(f"✓ Render xong: {path}")
        QMessageBox.information(self, "Done", f"Final video:\n{path}")

    def _on_render_fail(self, reason: str) -> None:
        self._append_log(f"❌ Render fail: {reason}")
        QMessageBox.critical(self, "Render fail", reason)

    def _cleanup_render(self) -> None:
        if self._render_worker is not None:
            self._render_worker.deleteLater()
        self._render_worker = None
        self.btn_render.setEnabled(
            self.project is not None and self.project.voice_mapping is not None
        )
        self._refresh_stop_button()

    # ------------------------------------------------------------------
    # Kdenlive XML export (Sprint 2 Phase 3)
    # ------------------------------------------------------------------

    def _on_export_kdenlive(self) -> None:
        if self.project is None:
            QMessageBox.warning(self, "Chưa load dự án", "Mở scenes.json trước.")
            return
        output_path = self.project.paths.root / "export.kdenlive"
        if output_path.exists():
            reply = QMessageBox.question(
                self, "File tồn tại",
                f"{output_path.name} đã có. Ghi đè?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        voice_dict = (
            self.project.voice_mapping.model_dump()
            if self.project.voice_mapping is not None else None
        )
        worker = ExportKdenliveWorker(
            project=self.project,
            voice_mapping=voice_dict,
            output_path=output_path,
            also_srt=True,
        )
        worker.log_message.connect(self._append_log)
        worker.export_done.connect(self._on_export_done)
        worker.export_failed.connect(self._on_export_failed)
        worker.finished.connect(self._cleanup_export)
        self._export_worker = worker
        self.btn_export_kdenlive.setEnabled(False)
        self._append_log("▶ Export Kdenlive XML...")
        worker.start()
        self._register_worker(worker)

    def _on_export_done(self, kpath: str, srt: str) -> None:
        msg = f"Đã xuất Kdenlive XML:\n{kpath}"
        if srt:
            msg += f"\n\nSubtitles SRT:\n{srt}"
        msg += (
            "\n\nMở Kdenlive → File → Open → chọn .kdenlive này.\n"
            "Lưu ý: effects/transitions/color chưa export — re-add manual nếu cần."
        )
        QMessageBox.information(self, "Export OK", msg)

    def _on_export_failed(self, reason: str) -> None:
        QMessageBox.critical(self, "Export fail", reason)

    def _cleanup_export(self) -> None:
        if self._export_worker is not None:
            self._export_worker.deleteLater()
        self._export_worker = None
        self.btn_export_kdenlive.setEnabled(self.project is not None)



def run() -> None:  # pragma: no cover (manual run)
    import asyncio

    from PyQt6.QtWidgets import QApplication
    from qasync import QEventLoop

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    win = MainWindow()
    win.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":  # pragma: no cover
    run()
