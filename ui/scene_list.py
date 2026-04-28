"""Scrollable list of SceneRow widgets bound to a Project."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from core.project import Project
from ui.scene_row import SceneRow


class SceneList(QScrollArea):
    """Owns a SceneRow per scene, syncs them to project state on demand.

    Re-emits row signals as (scene_id, ...) for the main window to handle.
    """

    regen_image_clicked = pyqtSignal(str)
    preview_image_clicked = pyqtSignal(str)
    preview_video_clicked = pyqtSignal(str)
    edit_clicked = pyqtSignal(str)
    warnings_clicked = pyqtSignal(str)
    selected_visual_changed = pyqtSignal(str, object)
    batch_selection_changed = pyqtSignal(int, int)  # (selected_count, total)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(2)
        self._layout.addStretch()
        self.setWidget(self._inner)

        self.rows: dict[str, SceneRow] = {}
        self.project: Project | None = None

    def bind_project(self, project: Project) -> None:
        self.project = project
        self._clear()

        for scene in project.scenes:
            row = SceneRow(scene.id, scene.visual_type)
            row.regen_image_clicked.connect(self.regen_image_clicked)
            row.preview_image_clicked.connect(self.preview_image_clicked)
            row.preview_video_clicked.connect(self.preview_video_clicked)
            row.edit_clicked.connect(self.edit_clicked)
            row.warnings_clicked.connect(self.warnings_clicked)
            row.selected_visual_changed.connect(self.selected_visual_changed)
            row.batch_selection_changed.connect(self._on_batch_toggled)
            row.apply_state(project.get_scene_state(scene.id))
            self.rows[scene.id] = row
            self._layout.insertWidget(self._layout.count() - 1, row)

        self._emit_selection()

    def selected_scene_ids(self) -> list[str]:
        return [sid for sid, row in self.rows.items() if row.batch_tick.isChecked()]

    def _on_batch_toggled(self, _scene_id: str, _checked: bool) -> None:
        self._emit_selection()

    def _emit_selection(self) -> None:
        self.batch_selection_changed.emit(len(self.selected_scene_ids()), len(self.rows))

    def refresh_row(self, scene_id: str) -> None:
        if not self.project or scene_id not in self.rows:
            return
        self.rows[scene_id].apply_state(self.project.get_scene_state(scene_id))

    def refresh_all(self) -> None:
        if not self.project:
            return
        for sid in self.rows:
            self.refresh_row(sid)

    def _clear(self) -> None:
        for row in self.rows.values():
            self._layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.rows.clear()
