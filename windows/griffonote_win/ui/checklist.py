"""Checklist editor: drag to reorder, checked items folded at the bottom (like Keep / the Android app)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton, QVBoxLayout,
                               QWidget)

from ..core.note import CheckItem
from . import icons


class _Handle(QLabel):
    pressed = Signal()
    moved = Signal(int)  # global y
    released = Signal()

    def __init__(self, color: str):
        super().__init__()
        self.setPixmap(icons.icon("drag", color, 20).pixmap(20, 20))
        self.setFixedSize(24, 28)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def mousePressEvent(self, event):
        self.pressed.emit()

    def mouseMoveEvent(self, event):
        self.moved.emit(int(event.globalPosition().y()))

    def mouseReleaseEvent(self, event):
        self.released.emit()


class _Edit(QLineEdit):
    backspace_on_empty = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Backspace and not self.text():
            self.backspace_on_empty.emit()
            return
        super().keyPressEvent(event)


class ItemRow(QWidget):
    toggled = Signal(object)
    edited = Signal()
    enter_pressed = Signal(object)
    remove_requested = Signal(object, bool)  # row, focus previous
    drag_started = Signal(object)
    drag_moved = Signal(object, int)
    drag_ended = Signal(object)

    def __init__(self, item: CheckItem, fg: str):
        super().__init__()
        self.checked = item.checked
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.handle: _Handle | None = None
        if not item.checked:
            self.handle = _Handle(fg)
            self.handle.pressed.connect(lambda: self.drag_started.emit(self))
            self.handle.moved.connect(lambda y: self.drag_moved.emit(self, y))
            self.handle.released.connect(lambda: self.drag_ended.emit(self))
            layout.addWidget(self.handle)
        else:
            layout.addSpacing(24)
        self.box = QCheckBox()
        self.box.setChecked(item.checked)
        self.box.toggled.connect(lambda _: self.toggled.emit(self))
        layout.addWidget(self.box)
        self.edit = _Edit(item.text)
        self.edit.setFrame(False)
        self.edit.setStyleSheet(
            "QLineEdit { background: transparent; border: none; font-size: 11pt; padding: 4px 0;"
            + (f" color: {fg}; }}" if not item.checked else f" color: {fg}; text-decoration: line-through; }}")
        )
        if item.checked:
            self.edit.setReadOnly(True)
        self.edit.textChanged.connect(lambda _: self.edited.emit())
        self.edit.returnPressed.connect(lambda: self.enter_pressed.emit(self))
        self.edit.backspace_on_empty.connect(lambda: self.remove_requested.emit(self, True))
        layout.addWidget(self.edit, 1)
        if not item.checked:
            close = QToolButton()
            close.setIcon(icons.icon("close", fg, 16))
            close.setAutoRaise(True)
            close.setFixedSize(28, 28)
            close.setToolTip("Supprimer l'élément")
            close.clicked.connect(lambda: self.remove_requested.emit(self, False))
            layout.addWidget(close)

    def item(self) -> CheckItem:
        return CheckItem(self.edit.text(), self.box.isChecked())


class ChecklistWidget(QWidget):
    changed = Signal()

    def __init__(self, fg: str):
        super().__init__()
        self.fg = fg
        self.expanded = False
        self._drag_row: ItemRow | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.open_box = QVBoxLayout()
        self.open_box.setSpacing(0)
        outer.addLayout(self.open_box)

        self.add_button = QPushButton("  Ajouter un élément")
        self.add_button.setIcon(icons.icon("add", fg, 20))
        self.add_button.setStyleSheet(f"QPushButton {{ color: {fg}; text-align: left; padding: 8px 12px; border-radius: 8px; }}")
        self.add_button.setFlat(True)
        self.add_button.clicked.connect(lambda: self.add_item(None))
        outer.addWidget(self.add_button)

        self.fold_button = QPushButton()
        self.fold_button.setStyleSheet(f"QPushButton {{ color: {fg}; text-align: left; padding: 8px 12px; border-radius: 8px; }}")
        self.fold_button.clicked.connect(self._toggle_fold)
        outer.addWidget(self.fold_button)
        self.done_box = QVBoxLayout()
        self.done_box.setSpacing(0)
        outer.addLayout(self.done_box)
        self._sync_chrome()

    # ---- model ----

    def set_items(self, items: list[CheckItem]) -> None:
        for box in (self.open_box, self.done_box):
            while box.count():
                w = box.takeAt(0).widget()
                if w:
                    w.deleteLater()
        for item in items:
            self._insert(item, None)
        self._sync_chrome()

    def items(self) -> list[CheckItem]:
        return [r.item() for r in self._rows(self.open_box)] + [r.item() for r in self._rows(self.done_box)]

    def count(self) -> int:
        return self.open_box.count() + self.done_box.count()

    def _rows(self, box: QVBoxLayout) -> list[ItemRow]:
        return [box.itemAt(i).widget() for i in range(box.count())]

    def _insert(self, item: CheckItem, index: int | None) -> ItemRow:
        row = ItemRow(item, self.fg)
        row.toggled.connect(self._on_toggled)
        row.edited.connect(self.changed)
        row.enter_pressed.connect(lambda r: self.add_item(r))
        row.remove_requested.connect(self._remove)
        row.drag_started.connect(self._drag_start)
        row.drag_moved.connect(self._drag_move)
        row.drag_ended.connect(self._drag_end)
        box = self.done_box if item.checked else self.open_box
        box.insertWidget(box.count() if index is None else index, row)
        return row

    def _sync_chrome(self) -> None:
        done = self.done_box.count()
        self.fold_button.setVisible(done > 0)
        label = "1 élément coché" if done == 1 else f"{done} éléments cochés"
        self.fold_button.setText("  " + label)
        self.fold_button.setIcon(icons.icon("expand_less" if self.expanded else "expand_more", self.fg, 20))
        for r in self._rows(self.done_box):
            r.setVisible(self.expanded)

    def _toggle_fold(self) -> None:
        self.expanded = not self.expanded
        self._sync_chrome()

    # ---- actions ----

    def add_item(self, after: ItemRow | None) -> None:
        index = self.open_box.indexOf(after) + 1 if after is not None else None
        row = self._insert(CheckItem("", False), index)
        row.edit.setFocus()
        self._sync_chrome()
        self.changed.emit()

    def _remove(self, row: ItemRow, focus_previous: bool) -> None:
        rows = self._rows(self.open_box)
        index = rows.index(row) if row in rows else -1
        box = self.open_box if row in rows else self.done_box
        box.removeWidget(row)
        row.deleteLater()
        if focus_previous and index > 0:
            rows[index - 1].edit.setFocus()
        self._sync_chrome()
        self.changed.emit()

    def _on_toggled(self, row: ItemRow) -> None:
        item = row.item()
        was_open = row in self._rows(self.open_box)
        (self.open_box if was_open else self.done_box).removeWidget(row)
        row.deleteLater()
        self._insert(item, None)  # checked -> end of the folded section; unchecked -> end of the open list
        self._sync_chrome()
        self.changed.emit()

    # ---- drag to reorder ----

    def _drag_start(self, row: ItemRow) -> None:
        self._drag_row = row
        row.setStyleSheet("ItemRow { background: rgba(128,128,128,0.18); border-radius: 8px; }")

    def _drag_move(self, row: ItemRow, global_y: int) -> None:
        if self._drag_row is not row:
            return
        rows = self._rows(self.open_box)
        y = self.mapFromGlobal(QPoint(0, global_y)).y()
        target = 0
        for other in rows:
            if other is row:
                continue
            centre = other.mapTo(self, QPoint(0, other.height() // 2)).y()
            if centre < y:
                target += 1
        if target != rows.index(row):
            self.open_box.removeWidget(row)
            self.open_box.insertWidget(target, row)
            self.changed.emit()

    def _drag_end(self, row: ItemRow) -> None:
        self._drag_row = None
        row.setStyleSheet("")
