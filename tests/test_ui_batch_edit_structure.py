import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.scene_list import SceneList

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


def test_scene_list_select_all_and_clear_selection_emit_counts():
    _app()
    scene_list = SceneList()
    counts: list[tuple[int, int]] = []
    scene_list.batch_selection_changed.connect(lambda selected, total: counts.append((selected, total)))

    class Row:
        def __init__(self) -> None:
            self.checked = True

        def is_batch_selected(self) -> bool:
            return self.checked

        def set_batch_selected(self, checked: bool) -> None:
            self.checked = checked

    scene_list.rows = {"1": Row(), "2": Row(), "3": Row()}  # type: ignore[assignment]

    scene_list.clear_selection()
    scene_list.select_all()

    assert counts[-2:] == [(0, 3), (3, 3)]


def test_main_window_exposes_batch_edit_and_selection_controls():
    _app()
    win = MainWindow()

    assert win.btn_batch_image.text() == "➕ Batch ảnh"
    assert win.btn_batch_video.text() == "🎞 Batch video"
    assert win.btn_batch_edit.text() == "🛠 Batch edit"
    assert win.btn_select_all.text() == "☑ All"
    assert win.btn_clear_selection.text() == "☐ Clear"
    assert not hasattr(win, "btn_process_voice")
