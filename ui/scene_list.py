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

    edit_clicked = pyqtSignal(str)
    visual_type_changed = pyqtSignal(str, str)  # scene_id, new_type
    effect_changed = pyqtSignal(str, str)  # scene_id, new_effect
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

        for idx, scene in enumerate(project.scenes, start=1):
            thumb = project.paths.find_image(idx)
            row = SceneRow(
                scene_id=scene.id,
                visual_type=scene.visual_type,
                effect=scene.effect or "no_effect",
                duration=int(scene.duration),
                thumbnail_path=thumb,
            )
            row.edit_clicked.connect(self.edit_clicked)
            row.visual_type_changed.connect(self.visual_type_changed)
            row.effect_changed.connect(self.effect_changed)
            row.batch_selection_changed.connect(self._on_batch_toggled)
            row.apply_state(project.get_scene_state(scene.id))
            self.rows[scene.id] = row
            self._layout.insertWidget(self._layout.count() - 1, row)

        self._emit_selection()

    def selected_scene_ids(self) -> list[str]:
        return [sid for sid, row in self.rows.items() if row.is_batch_selected()]

    def _on_batch_toggled(self, _scene_id: str, _checked: bool) -> None:
        self._emit_selection()

    def _emit_selection(self) -> None:
        self.batch_selection_changed.emit(len(self.selected_scene_ids()), len(self.rows))

    def refresh_row(self, scene_id: str) -> None:
        if not self.project or scene_id not in self.rows:
            return
        row = self.rows[scene_id]
        row.apply_state(self.project.get_scene_state(scene_id))
        # Source-of-truth for thumbnails is sources/ via auto-scan, so a
        # rename or re-generated image is picked up without extra plumbing.
        try:
            idx = self.project.scene_index(scene_id)
        except KeyError:
            idx = None
        thumb = self.project.paths.find_image(idx) if idx is not None else None
        row.set_thumbnail(thumb)
        scene = self.project.scenes_json.scene_by_id(scene_id)
        if scene is not None:
            row.update_visual_type(scene.visual_type)
            row.update_effect(scene.effect or "no_effect")
            row.update_duration(int(scene.duration))

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
