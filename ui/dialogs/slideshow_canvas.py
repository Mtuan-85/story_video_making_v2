"""SlideshowCanvas — QGraphicsView for polygon editing.

State machine (lighter than zone_animate's — no drawing new zones since
Claude already picked them):

    IDLE              - default; click polygon -> SELECTED, click empty -> stay IDLE
    SELECTED          - one zone selected; vertex handles visible
    EDITING_VERTEX    - dragging a vertex handle

Interactions:
    - Click polygon       → SELECTED
    - Click empty         → IDLE (deselect)
    - Drag vertex handle  → move vertex (Move command)
    - Right-click vertex  → context menu: Delete vertex
    - Right-click edge    → context menu: Insert vertex
    - Wheel               → zoom
    - Middle-drag / Space+drag → pan
    - Ctrl+0              → fit to view
    - Ctrl+1              → zoom 100%

Coordinate system: scene = source image pixels (1:1). Zoom/pan are
view transforms only; saved polygon coords stay in source pixels.

Emits:
    zone_selected(zone_id)         when a polygon is selected
    polygons_changed()             when any polygon's vertices change
"""

from __future__ import annotations

import colorsys
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QShortcut,
    QUndoCommand,
    QUndoStack,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QMenu,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zone_color(order: int) -> QColor:
    """Golden-angle HSV cycling for distinct per-zone colors."""
    hue = ((order - 1) * 137.5) % 360 / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.7, 0.9)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


def _pil_to_qpixmap(image: Image.Image) -> QPixmap:
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    w, h = image.size
    qimg = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


VERTEX_HANDLE_RADIUS = 6
VERTEX_HIT_RADIUS = 10
EDGE_HIT_TOLERANCE = 8


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class CanvasState(Enum):
    IDLE = auto()
    SELECTED = auto()
    EDITING_VERTEX = auto()


# ---------------------------------------------------------------------------
# Undo commands
# ---------------------------------------------------------------------------

class MoveVertexCommand(QUndoCommand):
    """Move one vertex of a zone polygon."""

    def __init__(
        self,
        canvas: "SlideshowCanvas",
        zone_id: int,
        vertex_idx: int,
        old_pos: Tuple[int, int],
        new_pos: Tuple[int, int],
    ):
        super().__init__(f"Move vertex zone={zone_id} idx={vertex_idx}")
        self.canvas = canvas
        self.zone_id = zone_id
        self.vertex_idx = vertex_idx
        self.old_pos = old_pos
        self.new_pos = new_pos

    def redo(self) -> None:
        self.canvas._set_vertex(self.zone_id, self.vertex_idx, self.new_pos)

    def undo(self) -> None:
        self.canvas._set_vertex(self.zone_id, self.vertex_idx, self.old_pos)


class DeleteVertexCommand(QUndoCommand):
    """Delete one vertex (only if polygon would still have ≥3 vertices)."""

    def __init__(self, canvas: "SlideshowCanvas", zone_id: int, vertex_idx: int):
        super().__init__(f"Delete vertex zone={zone_id} idx={vertex_idx}")
        self.canvas = canvas
        self.zone_id = zone_id
        self.vertex_idx = vertex_idx
        self.removed_pos: Optional[Tuple[int, int]] = None

    def redo(self) -> None:
        zone = self.canvas._zone_by_id(self.zone_id)
        if zone is None or len(zone["polygon"]) <= 3:
            return  # don't delete if would leave < 3 vertices
        self.removed_pos = tuple(zone["polygon"][self.vertex_idx])
        zone["polygon"].pop(self.vertex_idx)
        self.canvas._rebuild_zone(self.zone_id)

    def undo(self) -> None:
        if self.removed_pos is None:
            return
        zone = self.canvas._zone_by_id(self.zone_id)
        if zone is None:
            return
        zone["polygon"].insert(self.vertex_idx, list(self.removed_pos))
        self.canvas._rebuild_zone(self.zone_id)


class InsertVertexCommand(QUndoCommand):
    """Insert vertex on an edge (between two existing vertices)."""

    def __init__(
        self,
        canvas: "SlideshowCanvas",
        zone_id: int,
        edge_idx: int,
        pos: Tuple[int, int],
    ):
        super().__init__(f"Insert vertex zone={zone_id} edge={edge_idx}")
        self.canvas = canvas
        self.zone_id = zone_id
        self.edge_idx = edge_idx
        self.pos = pos

    def redo(self) -> None:
        zone = self.canvas._zone_by_id(self.zone_id)
        if zone is None:
            return
        # Insert after edge_idx (between edge_idx and edge_idx+1)
        zone["polygon"].insert(self.edge_idx + 1, list(self.pos))
        self.canvas._rebuild_zone(self.zone_id)

    def undo(self) -> None:
        zone = self.canvas._zone_by_id(self.zone_id)
        if zone is None:
            return
        zone["polygon"].pop(self.edge_idx + 1)
        self.canvas._rebuild_zone(self.zone_id)


# ---------------------------------------------------------------------------
# Vertex handle item
# ---------------------------------------------------------------------------

class _VertexHandle(QGraphicsEllipseItem):
    """Draggable vertex handle. Stores zone_id + vertex_idx."""

    def __init__(self, canvas: "SlideshowCanvas", zone_id: int, vertex_idx: int, x: float, y: float):
        r = VERTEX_HANDLE_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.canvas = canvas
        self.zone_id = zone_id
        self.vertex_idx = vertex_idx
        self.setPos(x, y)
        self.setBrush(QBrush(QColor(255, 255, 255)))
        self.setPen(QPen(QColor(0, 0, 0), 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True)
        self.setZValue(100)  # always on top
        self._drag_start_pos: Optional[Tuple[int, int]] = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = (int(self.x()), int(self.y()))
            self.canvas._state = CanvasState.EDITING_VERTEX
        elif event.button() == Qt.MouseButton.RightButton:
            self.canvas._show_vertex_menu(self.zone_id, self.vertex_idx, event.screenPos())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._drag_start_pos is not None:
            new_pos = (int(self.x()), int(self.y()))
            if new_pos != self._drag_start_pos:
                self.canvas.undo_stack.push(
                    MoveVertexCommand(
                        self.canvas, self.zone_id, self.vertex_idx,
                        self._drag_start_pos, new_pos,
                    )
                )
            self._drag_start_pos = None
        self.canvas._state = CanvasState.SELECTED

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self._drag_start_pos is not None:
            # Live update polygon as we drag (without pushing undo yet)
            zone = self.canvas._zone_by_id(self.zone_id)
            if zone is not None:
                pt = value
                zone["polygon"][self.vertex_idx] = [int(pt.x()), int(pt.y())]
                self.canvas._rebuild_polygon_only(self.zone_id)
        return super().itemChange(change, value)


# ---------------------------------------------------------------------------
# Main canvas
# ---------------------------------------------------------------------------

class SlideshowCanvas(QGraphicsView):
    """QGraphicsView for polygon editing on top of source image."""

    zone_selected = pyqtSignal(object)   # zone_id or None
    polygons_changed = pyqtSignal()      # any polygon mutated

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QBrush(QColor(32, 32, 32)))
        self.setMouseTracking(True)

        self._scene_obj = QGraphicsScene(self)
        self.setScene(self._scene_obj)

        self._state = CanvasState.IDLE
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._polygons: Dict[int, QGraphicsPolygonItem] = {}      # zone_id → polygon item
        self._vertex_handles: List[_VertexHandle] = []
        self._zones: List[dict] = []  # mutable list of zone dicts
        self._selected_zone_id: Optional[int] = None
        self._space_pressed = False
        self._panning = False
        self._pan_start = QPointF()

        self.undo_stack = QUndoStack(self)

        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo_stack.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self.undo_stack.redo)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self.fit_to_view)
        QShortcut(QKeySequence("Ctrl+1"), self, activated=self.zoom_100)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_image(self, image_path: Path) -> None:
        """Load source image into scene."""
        img = Image.open(image_path).convert("RGB")
        pixmap = _pil_to_qpixmap(img)

        if self._pixmap_item:
            self._scene_obj.removeItem(self._pixmap_item)
        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._pixmap_item.setZValue(0)
        self._scene_obj.addItem(self._pixmap_item)
        self._scene_obj.setSceneRect(QRectF(pixmap.rect()))

        self.fit_to_view()

    def set_zones(self, zones: List[dict]) -> None:
        """Set zones to display. Each zone dict needs 'zone_id', 'polygon', 'label'.

        IMPORTANT: stores reference, mutations affect outer list.
        """
        self._clear_polygons()
        self._zones = zones
        for zone_dict in zones:
            self._build_polygon_item(zone_dict)

    def get_zones(self) -> List[dict]:
        return self._zones

    def select_zone(self, zone_id: Optional[int]) -> None:
        """Programmatically select a zone."""
        if zone_id == self._selected_zone_id:
            return
        self._clear_vertex_handles()
        self._selected_zone_id = zone_id
        if zone_id is not None:
            self._show_vertex_handles(zone_id)
            self._state = CanvasState.SELECTED
        else:
            self._state = CanvasState.IDLE
        self.zone_selected.emit(zone_id)

    def fit_to_view(self) -> None:
        if self._pixmap_item:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_100(self) -> None:
        self.resetTransform()

    # ------------------------------------------------------------------
    # Internal — polygon rendering
    # ------------------------------------------------------------------

    def _clear_polygons(self) -> None:
        for item in self._polygons.values():
            self._scene_obj.removeItem(item)
        self._polygons.clear()
        self._clear_vertex_handles()

    def _clear_vertex_handles(self) -> None:
        for h in self._vertex_handles:
            self._scene_obj.removeItem(h)
        self._vertex_handles.clear()

    def _build_polygon_item(self, zone_dict: dict) -> None:
        zone_id = zone_dict["zone_id"]
        polygon = zone_dict.get("polygon", [])
        if len(polygon) < 3:
            return

        qpoly = QPolygonF([QPointF(p[0], p[1]) for p in polygon])
        item = QGraphicsPolygonItem(qpoly)
        color = _zone_color(zone_id)
        fill = QColor(color)
        fill.setAlpha(80)
        item.setBrush(QBrush(fill))
        item.setPen(QPen(color, 2))
        item.setZValue(10)
        item.setData(0, zone_id)  # store zone_id for hit-testing
        item.setAcceptHoverEvents(True)
        self._scene_obj.addItem(item)
        self._polygons[zone_id] = item

    def _rebuild_zone(self, zone_id: int) -> None:
        """Re-create polygon item + handles for a zone after mutation."""
        if zone_id in self._polygons:
            self._scene_obj.removeItem(self._polygons[zone_id])
            del self._polygons[zone_id]
        zone = self._zone_by_id(zone_id)
        if zone is not None:
            self._build_polygon_item(zone)
        if self._selected_zone_id == zone_id:
            self._clear_vertex_handles()
            self._show_vertex_handles(zone_id)
        self.polygons_changed.emit()

    def _rebuild_polygon_only(self, zone_id: int) -> None:
        """Update polygon shape without rebuilding handles (used during drag)."""
        zone = self._zone_by_id(zone_id)
        if zone is None or zone_id not in self._polygons:
            return
        polygon = zone.get("polygon", [])
        qpoly = QPolygonF([QPointF(p[0], p[1]) for p in polygon])
        self._polygons[zone_id].setPolygon(qpoly)

    def _show_vertex_handles(self, zone_id: int) -> None:
        zone = self._zone_by_id(zone_id)
        if zone is None:
            return
        for idx, (x, y) in enumerate(zone.get("polygon", [])):
            h = _VertexHandle(self, zone_id, idx, x, y)
            self._scene_obj.addItem(h)
            self._vertex_handles.append(h)

    def _set_vertex(self, zone_id: int, vertex_idx: int, pos: Tuple[int, int]) -> None:
        zone = self._zone_by_id(zone_id)
        if zone is None:
            return
        polygon = zone.get("polygon", [])
        if 0 <= vertex_idx < len(polygon):
            polygon[vertex_idx] = list(pos)
        self._rebuild_zone(zone_id)

    def _zone_by_id(self, zone_id: int) -> Optional[dict]:
        for z in self._zones:
            if z.get("zone_id") == zone_id:
                return z
        return None

    # ------------------------------------------------------------------
    # Mouse / keyboard interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_pressed
        ):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene_obj.itemAt(scene_pos, self.transform())

        if isinstance(item, _VertexHandle):
            # Let handle itself process the event
            super().mousePressEvent(event)
            return

        if isinstance(item, QGraphicsPolygonItem):
            zone_id = item.data(0)
            if event.button() == Qt.MouseButton.LeftButton:
                self.select_zone(zone_id)
            elif event.button() == Qt.MouseButton.RightButton:
                self._show_polygon_menu(zone_id, scene_pos, event.screenPos())
            return

        # Click on empty area → deselect
        if event.button() == Qt.MouseButton.LeftButton:
            self.select_zone(None)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Zoom
        zoom_factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(zoom_factor, zoom_factor)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().keyReleaseEvent(event)

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def _show_polygon_menu(self, zone_id: int, scene_pos: QPointF, screen_pos) -> None:
        """Right-click on polygon body — offer to insert vertex at click point."""
        # Find nearest edge to scene_pos
        zone = self._zone_by_id(zone_id)
        if zone is None:
            return

        polygon = zone.get("polygon", [])
        if len(polygon) < 2:
            return

        # Find closest edge
        click_x, click_y = scene_pos.x(), scene_pos.y()
        best_edge = -1
        best_dist = float("inf")
        for i in range(len(polygon)):
            x1, y1 = polygon[i]
            x2, y2 = polygon[(i + 1) % len(polygon)]
            d = _point_to_segment_dist(click_x, click_y, x1, y1, x2, y2)
            if d < best_dist:
                best_dist = d
                best_edge = i

        menu = QMenu(self)
        a_select = menu.addAction("✔ Select zone")
        a_insert = menu.addAction(f"➕ Insert vertex (edge {best_edge})")
        a_close = menu.addAction("× Cancel")

        chosen = menu.exec(screen_pos.toPoint())
        if chosen is a_select:
            self.select_zone(zone_id)
        elif chosen is a_insert and best_edge >= 0:
            self.undo_stack.push(
                InsertVertexCommand(
                    self, zone_id, best_edge,
                    (int(click_x), int(click_y)),
                )
            )
            self.select_zone(zone_id)

    def _show_vertex_menu(self, zone_id: int, vertex_idx: int, screen_pos) -> None:
        menu = QMenu(self)
        zone = self._zone_by_id(zone_id)
        can_delete = zone is not None and len(zone.get("polygon", [])) > 3
        a_del = menu.addAction("🗑 Delete vertex")
        a_del.setEnabled(can_delete)

        chosen = menu.exec(screen_pos.toPoint())
        if chosen is a_del and can_delete:
            self.undo_stack.push(DeleteVertexCommand(self, zone_id, vertex_idx))


# ---------------------------------------------------------------------------
# Geometry helper
# ---------------------------------------------------------------------------

def _point_to_segment_dist(px, py, x1, y1, x2, y2) -> float:
    """Distance from point (px,py) to line segment (x1,y1)-(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5
