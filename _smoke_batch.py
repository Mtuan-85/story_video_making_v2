"""Smoke test: auto-connect + click batch on SCENE-01, capture trace."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop

from core.project import Project
from ui.main_window import MainWindow


def p(*args):
    print(*args, flush=True)


def main():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    win = MainWindow()
    win.show()

    QMessageBox.question = staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok)

    async def auto():
        try:
            p("[T+0] start")
            await asyncio.sleep(1)
            p("[T+1] click Connect")
            win.connection_panel._toggle_connect()
            for s in range(15):
                await asyncio.sleep(1)
                if win.image_engine is not None:
                    p(f"[T+{1 + s + 1}] engine READY")
                    break
                p(f"[T+{1 + s + 1}] waiting engine...")
            if win.image_engine is None:
                p("[ERR] engine never ready")
                app.quit()
                return

            p("[T+x] loading project test_run")
            win.project = Project.load(Path("test_run"))
            win.scene_list.bind_project(win.project)
            for sid, row in win.scene_list.rows.items():
                row.batch_tick.setChecked(sid == "SCENE-01")
            p(f"[ready] selected={win.scene_list.selected_scene_ids()}")
            p(f"[ready] btn_enabled={win.btn_batch_image.isEnabled()}")

            p("[ready] >>> CLICK BATCH <<<")
            win._start_batch_image()
            for sec in range(60):
                await asyncio.sleep(2)
                alive = win._batch_worker is not None and win._batch_worker.isRunning()
                p(f"[t+{(sec + 1) * 2}s] worker_alive={alive}, page_url={win.image_engine.page.url if win.image_engine else None}")
                if not alive:
                    break
            p("[end] quit")
            app.quit()
        except Exception as e:
            import traceback
            p(f"[FATAL] {e}")
            p(traceback.format_exc())
            app.quit()

    asyncio.ensure_future(auto())
    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
