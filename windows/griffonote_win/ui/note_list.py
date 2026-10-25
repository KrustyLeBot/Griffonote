from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QListWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..core.note import Note
from . import theme

NOTE_ROLE = Qt.ItemDataRole.UserRole


def preview(note: Note) -> str:
    lines = [ln for ln in note.plain_body().split("\n") if ln.strip() and not ln.lstrip().startswith("![")]
    return "\n".join(ln.replace("**", "") for ln in lines[:2])


class NoteDelegate(QStyledItemDelegate):
    """Draws each note as a rounded card, like the Android list."""

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), 84)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        note: Note = index.data(NOTE_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = option.rect.adjusted(6, 3, -6, -3)
        palette = option.palette
        background = theme.note_background(note.color) or palette.base().color()
        foreground = theme.note_foreground(note.color) or palette.text().color()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setBrush(background)
        painter.setPen(QPen(palette.highlight().color() if selected else palette.mid().color(), 2 if selected else 1))
        painter.drawRoundedRect(card, 10, 10)

        inner = card.adjusted(12, 8, -12, -8)
        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(foreground)
        metrics = QFontMetrics(title_font)
        title = ("📌 " if note.pinned else "") + (note.title or "Sans titre")
        painter.drawText(QRect(inner.left(), inner.top(), inner.width(), metrics.height()),
                         Qt.AlignmentFlag.AlignLeft, metrics.elidedText(title, Qt.TextElideMode.ElideRight, inner.width()))

        body_font = QFont(option.font)
        painter.setFont(body_font)
        dim = QColor(foreground)
        dim.setAlpha(190)
        painter.setPen(dim)
        body_metrics = QFontMetrics(body_font)
        y = inner.top() + metrics.height() + 2
        for line in preview(note).split("\n"):
            if not line:
                continue
            painter.drawText(QRect(inner.left(), y, inner.width(), body_metrics.height()), Qt.AlignmentFlag.AlignLeft,
                             body_metrics.elidedText(line, Qt.TextElideMode.ElideRight, inner.width()))
            y += body_metrics.height()
        tags = "  ".join(f"#{x}" for x in note.labels[:3]) + ("   ⚠ conflit" if note.conflict else "")
        if tags:
            small = QFont(option.font)
            small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
            painter.setFont(small)
            painter.setPen(dim)
            painter.drawText(QRect(inner.left(), inner.bottom() - 14, inner.width(), 16), Qt.AlignmentFlag.AlignLeft, tags)
        painter.restore()


class NoteList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setItemDelegate(NoteDelegate())
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
