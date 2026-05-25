"""SlideshowEditDialog — V3 zone editor for re-rendering slideshow.

Triggered when user clicks 🛠 button on a scene with edit.status='ready'.
Allows user to:
  - Edit polygons (drag vertex, add, delete)
  - Edit per-zone animation / emphasis / sound / timing
  - Re-render (skip Claude, use current zones)
  - Preview rendered MP4 (system player)

Loads from zones_json_path saved by previous slideshow render.
Re-render output overwrites the current video path.

Layout:
    ┌──────────────────┬──────────────┐
    │                  │ Zone table:  │
    │     Canvas       │ # Label Anim │
    │     (image +     │ Emp Sound t  │
    │      polygons    │              │
    │      editable)   │ ↩ Undo ↪ Redo│
    │                  │ ▶ Preview MP4│
    │                  │ 🔄 Re-render │
    │                  │ Đóng         │
    └──────────────────┴──────────────┘
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from loguru import logger as log
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.slideshow_canvas import SlideshowCanvas
from ui.dialogs.slideshow_zone_ops import (
    add_default_zone,
    apply_sound_to_all,
    delete_zone,
    move_zone,
    resequence_zones,
)


# Animation catalogs (sync with slideshow/animations.py DEFAULTS)
ENTRY_ANIMATIONS = [
    "fade_in",
    "scale_pop",
    "slide_in_left",
    "slide_in_right",
    "slide_in_top",
    "slide_in_bottom",
    "drop_in",
]
EMPHASIS_OPTIONS = ["none", "pulse", "glow", "shake"]
SOUNDS = ["pop", "flip", "whoosh", "swoosh", "ding"]


class SlideshowEditDialog(QDialog):
    """V3 zone editor: edit polygons + animation/timing, re-render skip Claude."""

    rerender_requested = pyqtSignal(str)  # scene_id

    def __init__(
        self,
        scene_id: str,
        scene_state: dict,
        project_root: Path,
        zones_json_path: Path,
        video_path: Optional[Path],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.scene_id = scene_id
        self.scene_state = scene_state or {}
        self.project_root = Path(project_root)
        self.zones_json_path = Path(zones_json_path)
        self.video_path = Path(video_path) if video_path else None

        self.setWindowTitle(f"Edit Slideshow — {scene_id}")
        self.resize(1280, 800)

        # Loaded data
        self._zones: list = []
        self._image_path: Optional[Path] = None
        self._duration: float = 8.0
        self._aspect_ratio: str = "16:9"
        self._bg_color = (255, 255, 255)
        self._hint: str = ""
        self._dirty = False

        self._load_zones_json()
        self._build_ui()
        self._populate_table()

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load_zones_json(self) -> None:
        """Load zones JSON saved by previous render."""
        if not self.zones_json_path.exists():
            raise FileNotFoundError(f"Zones JSON not found: {self.zones_json_path}")

        with self.zones_json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # image_path could be absolute or relative-to-project
        img_p = Path(data["image_path"])
        if not img_p.is_absolute():
            img_p = self.project_root / img_p
        self._image_path = img_p

        self._duration = float(data.get("duration", 8.0))
        self._aspect_ratio = data.get("aspect_ratio", "16:9")
        self._bg_color = tuple(data.get("bg_color", (255, 255, 255)))
        self._hint = data.get("hint", "")
        self._zones = data.get("zones", [])

    def _save_zones_json(self) -> None:
        """Save edited zones back to JSON."""
        data = {
            "version": 1,
            "image_path": str(self._image_path).replace("\\", "/"),
            "image_size": list(self._zones[0].get("_image_size", [])) if self._zones else None,
            "bg_color": list(self._bg_color),
            "duration": self._duration,
            "aspect_ratio": self._aspect_ratio,
            "hint": self._hint,
            "zones": self._zones,
        }
        # Preserve image_size from original if not in zones
        if not data.get("image_size") and self.zones_json_path.exists():
            with self.zones_json_path.open("r", encoding="utf-8") as f:
                old = json.load(f)
            data["image_size"] = old.get("image_size")

        tmp = self.zones_json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.zones_json_path)
        self._dirty = False

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # Left: canvas
        self.canvas = SlideshowCanvas()
        if self._image_path and self._image_path.exists():
            self.canvas.load_image(self._image_path)
        self.canvas.set_zones(self._zones)
        self.canvas.zone_selected.connect(self._on_canvas_zone_selected)
        self.canvas.polygons_changed.connect(self._on_polygons_changed)
        splitter.addWidget(self.canvas)

        # Right: panel
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # Info header
        info = QLabel(
            f"<b>{self.scene_id}</b> · {self._duration}s · {self._aspect_ratio}<br>"
            f"<small style='color:#666'>BG: RGB{self._bg_color} · hint: {self._hint or '(none)'}</small>"
        )
        info.setWordWrap(True)
        right_layout.addWidget(info)

        # Zone table
        right_layout.addWidget(QLabel("<b>Zones:</b>"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["#", "Label", "Animation", "Emphasis", "Sound", "In→Out (s)"]
        )
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # combos handle edits
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        right_layout.addWidget(self.table, 1)

        # Bulk sound controls
        sound_all_row = QHBoxLayout()
        sound_all_row.addWidget(QLabel("Sound all:"))
        self.sound_all_combo = QComboBox()
        self.sound_all_combo.addItems(SOUNDS)
        self.sound_all_combo.setCurrentText("ding")
        sound_all_row.addWidget(self.sound_all_combo, 1)
        b_sound_all = QPushButton("Apply")
        b_sound_all.setToolTip("Áp dụng sound này cho tất cả zones")
        b_sound_all.clicked.connect(self._on_apply_sound_all)
        sound_all_row.addWidget(b_sound_all)
        right_layout.addLayout(sound_all_row)

        # Zone structure controls
        zone_ops = QHBoxLayout()
        b_add = QPushButton("+ Add Zone")
        b_add.setToolTip("Thêm zone chữ nhật ở giữa ảnh, rồi kéo vertex để chỉnh polygon")
        b_add.clicked.connect(self._on_add_zone)
        zone_ops.addWidget(b_add)
        b_up = QPushButton("↑ Up")
        b_up.setToolTip("Đưa zone đang chọn lên trước trong thứ tự render/timing")
        b_up.clicked.connect(self._on_move_up)
        zone_ops.addWidget(b_up)
        b_down = QPushButton("↓ Down")
        b_down.setToolTip("Đưa zone đang chọn xuống sau trong thứ tự render/timing")
        b_down.clicked.connect(self._on_move_down)
        zone_ops.addWidget(b_down)
        b_delete = QPushButton("× Delete")
        b_delete.setToolTip("Xóa zone đang chọn")
        b_delete.clicked.connect(self._on_delete_zone)
        zone_ops.addWidget(b_delete)
        right_layout.addLayout(zone_ops)

        # Undo/redo controls
        undo_row = QHBoxLayout()
        b_undo = QPushButton("↩ Undo")
        b_undo.clicked.connect(self.canvas.undo_stack.undo)
        b_redo = QPushButton("↪ Redo")
        b_redo.clicked.connect(self.canvas.undo_stack.redo)
        undo_row.addWidget(b_undo)
        undo_row.addWidget(b_redo)
        undo_row.addStretch()
        right_layout.addLayout(undo_row)

        # Preview / Re-render / Folder / Close
        actions = QVBoxLayout()
        self.b_preview = QPushButton("▶ Preview MP4 (system player)")
        self.b_preview.setToolTip("Mở MP4 hiện tại bằng player hệ thống")
        self.b_preview.setEnabled(self.video_path is not None and self.video_path.exists())
        self.b_preview.clicked.connect(self._on_preview)
        actions.addWidget(self.b_preview)

        self.b_rerender = QPushButton("🔄 Re-render (skip Claude)")
        self.b_rerender.setStyleSheet("font-weight:bold; padding:8px;")
        self.b_rerender.setToolTip("Save zones → re-render với polygons + timing hiện tại")
        self.b_rerender.clicked.connect(self._on_rerender)
        actions.addWidget(self.b_rerender)

        b_folder = QPushButton("📁 Open edit folder")
        b_folder.clicked.connect(self._open_folder)
        actions.addWidget(b_folder)

        b_close = QPushButton("Đóng")
        b_close.clicked.connect(self._on_close)
        actions.addWidget(b_close)

        right_layout.addLayout(actions)

        splitter.addWidget(right)
        splitter.setSizes([880, 380])

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._on_rerender)
        QShortcut(QKeySequence("Escape"), self, activated=self._on_close)

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        resequence_zones(self._zones)
        self.table.setRowCount(len(self._zones))
        for row, zone in enumerate(self._zones):
            zone_id = zone.get("zone_id", row + 1)

            # # column
            it = QTableWidgetItem(str(zone_id))
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, it)

            # Label
            lbl = QTableWidgetItem(zone.get("label", ""))
            lbl.setFlags(lbl.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, lbl)

            # Animation combo
            anim_combo = QComboBox()
            anim_combo.addItems(ENTRY_ANIMATIONS)
            cur_anim = zone.get("animation", "fade_in")
            if cur_anim in ENTRY_ANIMATIONS:
                anim_combo.setCurrentText(cur_anim)
            anim_combo.currentTextChanged.connect(
                lambda v, r=row: self._on_anim_changed(r, v)
            )
            self.table.setCellWidget(row, 2, anim_combo)

            # Emphasis combo
            emp_combo = QComboBox()
            emp_combo.addItems(EMPHASIS_OPTIONS)
            cur_emp = zone.get("emphasis", "none")
            if cur_emp in EMPHASIS_OPTIONS:
                emp_combo.setCurrentText(cur_emp)
            emp_combo.currentTextChanged.connect(
                lambda v, r=row: self._on_emp_changed(r, v)
            )
            self.table.setCellWidget(row, 3, emp_combo)

            # Sound combo
            snd_combo = QComboBox()
            snd_combo.addItems(SOUNDS)
            cur_snd = zone.get("sound", "ding")
            if cur_snd in SOUNDS:
                snd_combo.setCurrentText(cur_snd)
            snd_combo.currentTextChanged.connect(
                lambda v, r=row: self._on_sound_changed(r, v)
            )
            self.table.setCellWidget(row, 4, snd_combo)

            # Timing widget (2 spinboxes)
            timing = QWidget()
            tlayout = QHBoxLayout(timing)
            tlayout.setContentsMargins(2, 0, 2, 0)
            sb_in = QDoubleSpinBox()
            sb_in.setRange(0.0, 60.0)
            sb_in.setDecimals(2)
            sb_in.setSingleStep(0.1)
            sb_in.setValue(float(zone.get("appear_at", 0.0)))
            sb_in.valueChanged.connect(
                lambda v, r=row: self._on_appear_changed(r, v)
            )
            sb_out = QDoubleSpinBox()
            sb_out.setRange(0.0, 60.0)
            sb_out.setDecimals(2)
            sb_out.setSingleStep(0.1)
            sb_out.setValue(float(zone.get("end_at", 0.5)))
            sb_out.valueChanged.connect(
                lambda v, r=row: self._on_end_changed(r, v)
            )
            tlayout.addWidget(sb_in)
            tlayout.addWidget(QLabel("→"))
            tlayout.addWidget(sb_out)
            self.table.setCellWidget(row, 5, timing)

    def _on_table_cell_clicked(self, row: int, _col: int) -> None:
        """Click row → select corresponding zone on canvas."""
        if 0 <= row < len(self._zones):
            zone_id = self._zones[row].get("zone_id")
            if zone_id is not None:
                self.canvas.select_zone(zone_id)

    def _on_canvas_zone_selected(self, zone_id) -> None:
        """Canvas zone selection → highlight corresponding table row."""
        if zone_id is None:
            self.table.clearSelection()
            return
        for row, zone in enumerate(self._zones):
            if zone.get("zone_id") == zone_id:
                self.table.selectRow(row)
                break

    def _selected_zone_id(self) -> Optional[int]:
        row = self.table.currentRow()
        if 0 <= row < len(self._zones):
            return int(self._zones[row].get("zone_id", row + 1))
        return None

    def _refresh_zones_view(self, select_zone_id: Optional[int] = None) -> None:
        self.canvas.set_zones(self._zones)
        self._populate_table()
        if select_zone_id is not None:
            for row, zone in enumerate(self._zones):
                if int(zone.get("zone_id", -1)) == int(select_zone_id):
                    self.table.selectRow(row)
                    self.canvas.select_zone(select_zone_id)
                    break
        self._dirty = True

    def _on_polygons_changed(self) -> None:
        self._dirty = True

    def _on_anim_changed(self, row: int, value: str) -> None:
        if 0 <= row < len(self._zones):
            self._zones[row]["animation"] = value
            self._dirty = True

    def _on_emp_changed(self, row: int, value: str) -> None:
        if 0 <= row < len(self._zones):
            self._zones[row]["emphasis"] = value
            self._dirty = True

    def _on_sound_changed(self, row: int, value: str) -> None:
        if 0 <= row < len(self._zones):
            self._zones[row]["sound"] = value
            self._dirty = True

    def _on_apply_sound_all(self) -> None:
        sound = self.sound_all_combo.currentText()
        if sound not in SOUNDS:
            return
        apply_sound_to_all(self._zones, sound)
        self._populate_table()
        self._dirty = True

    def _on_appear_changed(self, row: int, value: float) -> None:
        if 0 <= row < len(self._zones):
            self._zones[row]["appear_at"] = round(value, 2)
            self._dirty = True

    def _on_end_changed(self, row: int, value: float) -> None:
        if 0 <= row < len(self._zones):
            self._zones[row]["end_at"] = round(value, 2)
            self._dirty = True

    def _on_add_zone(self) -> None:
        image_size = (1280, 720)
        if self._image_path and self._image_path.exists():
            from PIL import Image

            with Image.open(self._image_path) as img:
                image_size = img.size
        template = self._zones[-1] if self._zones else None
        zone = add_default_zone(self._zones, image_size=image_size, template=template)
        self._refresh_zones_view(int(zone["zone_id"]))

    def _on_move_up(self) -> None:
        zone_id = self._selected_zone_id()
        if zone_id is None:
            return
        if move_zone(self._zones, zone_id, -1):
            self._refresh_zones_view(zone_id)

    def _on_move_down(self) -> None:
        zone_id = self._selected_zone_id()
        if zone_id is None:
            return
        if move_zone(self._zones, zone_id, 1):
            self._refresh_zones_view(zone_id)

    def _on_delete_zone(self) -> None:
        zone_id = self._selected_zone_id()
        if zone_id is None:
            return
        if len(self._zones) <= 1:
            QMessageBox.information(self, "Không thể xóa", "Cần giữ ít nhất 1 zone.")
            return
        reply = QMessageBox.question(
            self,
            "Xác nhận xóa",
            f"Xóa zone {zone_id}?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        delete_zone(self._zones, zone_id)
        next_id = int(self._zones[min(self.table.currentRow(), len(self._zones) - 1)]["zone_id"])
        self._refresh_zones_view(next_id)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_preview(self) -> None:
        if self.video_path and self.video_path.exists():
            try:
                os.startfile(str(self.video_path))
            except Exception as e:
                log.error(f"Open in system player failed: {e}")
                QMessageBox.warning(self, "Lỗi", f"Không mở được file: {e}")

    def _on_rerender(self) -> None:
        """Save zones + emit signal to trigger re-render."""
        try:
            self._save_zones_json()
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không lưu được zones JSON: {e}")
            return

        self.rerender_requested.emit(self.scene_id)
        self.accept()

    def _open_folder(self) -> None:
        try:
            os.startfile(str(self.zones_json_path.parent))
        except Exception:
            pass

    def _on_close(self) -> None:
        if self._dirty:
            reply = QMessageBox.question(
                self,
                "Có thay đổi chưa lưu",
                "Lưu thay đổi vào zones JSON trước khi đóng?\n\n"
                "Yes = Save & Đóng (chưa re-render)\n"
                "No = Bỏ thay đổi\n"
                "Cancel = Tiếp tục edit",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    self._save_zones_json()
                except Exception as e:
                    QMessageBox.critical(self, "Lỗi", f"Save failed: {e}")
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        self.reject()
