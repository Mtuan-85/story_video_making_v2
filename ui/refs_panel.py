"""Reference Images panel — multi-ref upload (max 5) for image gen.

Drives project state fields ``image_refs`` + ``use_refs_for_image`` via
the ``refs_changed`` signal. Owner (MainWindow) wires that signal to the
loaded Project's setters.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MAX_REFS = 5


class RefImagesPanel(QGroupBox):
    """Side-by-side companion to the Project box. Disabled until a project loads."""

    refs_changed = pyqtSignal(list, bool)  # (paths, use_refs)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Reference Images (Image gen)", parent)
        self._refs: list[str] = []
        self._build_ui()
        self.setMinimumWidth(280)
        self.setMaximumWidth(400)
        self.setEnabled(False)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self.chk_use = QCheckBox("Use refs for image gen")
        self.chk_use.toggled.connect(self._on_use_toggled)
        layout.addWidget(self.chk_use)

        browse_row = QHBoxLayout()
        self.btn_browse = QPushButton("📁 Browse...")
        self.btn_browse.clicked.connect(self._on_browse)
        browse_row.addWidget(self.btn_browse)

        self.lbl_count = QLabel(f"(0/{MAX_REFS})")
        self.lbl_count.setStyleSheet("color:#666;")
        browse_row.addWidget(self.lbl_count)
        browse_row.addStretch()
        layout.addLayout(browse_row)

        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(140)
        layout.addWidget(self.list_widget)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_state(self, paths: list[str], use_refs: bool) -> None:
        self._refs = list(paths)[:MAX_REFS]
        # Block signals while restoring so we don't double-write to project state.
        prev = self.chk_use.blockSignals(True)
        self.chk_use.setChecked(use_refs)
        self.chk_use.blockSignals(prev)
        self._refresh_list()

    def get_paths(self) -> list[str]:
        return list(self._refs)

    def get_use_refs(self) -> bool:
        return self.chk_use.isChecked()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_use_toggled(self, checked: bool) -> None:
        self.refs_changed.emit(self._refs, checked)

    def _on_browse(self) -> None:
        if len(self._refs) >= MAX_REFS:
            QMessageBox.information(
                self,
                "Max refs",
                f"Đã đạt giới hạn {MAX_REFS} refs. Remove bớt trước khi add.",
            )
            return

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn ref images",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not files:
            return

        remaining = MAX_REFS - len(self._refs)
        to_add = files[:remaining]
        if len(files) > remaining:
            QMessageBox.information(
                self,
                "Limit reached",
                f"Chỉ add {remaining} files. Bỏ {len(files) - remaining} file (quá max {MAX_REFS}).",
            )

        self._refs.extend(to_add)
        self._refresh_list()
        self.refs_changed.emit(self._refs, self.chk_use.isChecked())

    def _on_remove(self, idx: int) -> None:
        if 0 <= idx < len(self._refs):
            removed = self._refs.pop(idx)
            log.info(f"Removed ref: {removed}")
            self._refresh_list()
            self.refs_changed.emit(self._refs, self.chk_use.isChecked())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        self.list_widget.clear()

        for i, path in enumerate(self._refs):
            item = QListWidgetItem()
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(4, 2, 4, 2)

            name = Path(path).name
            label = QLabel(f"{i + 1}. {name}")
            label.setToolTip(path)
            row.addWidget(label)
            row.addStretch()

            btn_remove = QPushButton("✗ Remove")
            btn_remove.setMaximumWidth(80)
            btn_remove.clicked.connect(lambda _checked=False, idx=i: self._on_remove(idx))
            row.addWidget(btn_remove)

            item.setSizeHint(row_widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row_widget)

        self.lbl_count.setText(f"({len(self._refs)}/{MAX_REFS})")
        self.btn_browse.setEnabled(len(self._refs) < MAX_REFS)
