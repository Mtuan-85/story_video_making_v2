"""Character reference setup panel for image generation."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.ref_mapping import CharacterRef, RefMapping


class RefImagesPanel(QGroupBox):
    """Project-level ref mapping editor: style ref + one row per character."""

    mapping_saved = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Reference Setup", parent)
        self._mapping = RefMapping()
        self._character_names: list[str] = []
        self._path_labels: dict[str, QLabel] = {}
        self._enabled_checks: dict[str, QCheckBox] = {}
        self._build_ui()
        self.setMinimumWidth(320)
        self.setMaximumWidth(520)
        self.setEnabled(False)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(6)

        self.chk_use = QCheckBox("Use refs for image gen")
        self.chk_use.toggled.connect(self._on_use_toggled)
        outer.addWidget(self.chk_use)

        self.chk_include_style = QCheckBox("Use style ref with character scenes")
        self.chk_include_style.toggled.connect(self._on_include_style_toggled)
        outer.addWidget(self.chk_include_style)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.rows_widget = QWidget()
        self.rows_layout = QGridLayout(self.rows_widget)
        self.rows_layout.setColumnStretch(1, 1)
        self.scroll.setWidget(self.rows_widget)
        outer.addWidget(self.scroll, 1)

        actions = QHBoxLayout()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#666;")
        actions.addWidget(self.lbl_status, 1)
        self.btn_save = QPushButton("Save refs")
        self.btn_save.clicked.connect(self._on_save)
        actions.addWidget(self.btn_save)
        outer.addLayout(actions)

    def set_mapping(self, mapping: RefMapping, character_names: list[str]) -> None:
        self._mapping = mapping
        self._character_names = sorted(character_names)
        self._rebuild_rows()

    def current_mapping(self) -> RefMapping:
        return self._mapping

    def set_status(self, text: str, ok: bool) -> None:
        color = "#2e7d32" if ok else "#c62828"
        self.lbl_status.setStyleSheet(f"color:{color};")
        self.lbl_status.setText(text)

    def _rebuild_rows(self) -> None:
        prev = self.chk_use.blockSignals(True)
        self.chk_use.setChecked(self._mapping.use_refs_for_image)
        self.chk_use.blockSignals(prev)
        prev = self.chk_include_style.blockSignals(True)
        self.chk_include_style.setChecked(self._mapping.include_style_ref_with_character)
        self.chk_include_style.blockSignals(prev)

        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._path_labels.clear()
        self._enabled_checks.clear()

        self._add_ref_row(0, "Style / Background", "__style__", self._mapping.style_ref)
        for row, name in enumerate(self._character_names, start=1):
            ref = self._mapping.characters.setdefault(name, CharacterRef())
            self._add_ref_row(row, name, name, ref)

    def _add_ref_row(self, row: int, title: str, key: str, ref: CharacterRef) -> None:
        enabled = QCheckBox()
        enabled.setChecked(ref.enabled)
        enabled.toggled.connect(lambda checked, k=key: self._on_ref_enabled(k, checked))
        self._enabled_checks[key] = enabled
        self.rows_layout.addWidget(enabled, row, 0)

        label = QLabel(title)
        label.setToolTip(title)
        self.rows_layout.addWidget(label, row, 1)

        path_label = QLabel(Path(ref.path).name if ref.path else "(missing)")
        path_label.setToolTip(ref.path)
        path_label.setStyleSheet("color:#444;")
        self._path_labels[key] = path_label
        self.rows_layout.addWidget(path_label, row, 2)

        browse = QPushButton("Browse")
        browse.clicked.connect(lambda _checked=False, k=key: self._browse_ref(k))
        self.rows_layout.addWidget(browse, row, 3)

        clear = QPushButton("Clear")
        clear.clicked.connect(lambda _checked=False, k=key: self._set_ref_path(k, ""))
        self.rows_layout.addWidget(clear, row, 4)

    def _ref_for_key(self, key: str) -> CharacterRef:
        if key == "__style__":
            return self._mapping.style_ref
        return self._mapping.characters.setdefault(key, CharacterRef())

    def _on_use_toggled(self, checked: bool) -> None:
        self._mapping.use_refs_for_image = bool(checked)

    def _on_include_style_toggled(self, checked: bool) -> None:
        self._mapping.include_style_ref_with_character = bool(checked)

    def _on_ref_enabled(self, key: str, checked: bool) -> None:
        self._ref_for_key(key).enabled = bool(checked)

    def _browse_ref(self, key: str) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn reference image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if file_path:
            self._set_ref_path(key, file_path)

    def _set_ref_path(self, key: str, path: str) -> None:
        ref = self._ref_for_key(key)
        ref.path = path
        label = self._path_labels.get(key)
        if label is not None:
            label.setText(Path(path).name if path else "(missing)")
            label.setToolTip(path)

    def _on_save(self) -> None:
        if not self._mapping.use_refs_for_image:
            reply = QMessageBox.question(
                self,
                "Refs disabled",
                "Use refs đang tắt. Save trạng thái này?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.mapping_saved.emit(self._mapping)
