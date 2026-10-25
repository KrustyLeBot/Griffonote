from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QKeyEvent, QSyntaxHighlighter, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from ..core.note import COLORS, DEFAULT_COLOR, Note
from . import theme

_LIST_RE = re.compile(r"^(\s*[-*+] )(\[[ xX]\] )?(.*)$")
_TASK_RE = re.compile(r"^(\s*[-*+] )\[([ xX])\] ?(.*)$")


class MarkdownHighlighter(QSyntaxHighlighter):
    """Light styling so the Markdown stays readable without being the star of the show."""

    def __init__(self, document):
        super().__init__(document)
        dim = QColor("#888888")
        self._marker = QTextCharFormat()
        self._marker.setForeground(dim)
        self._bold = QTextCharFormat()
        self._bold.setFontWeight(QFont.Weight.Bold)
        self._italic = QTextCharFormat()
        self._italic.setFontItalic(True)
        self._heading = QTextCharFormat()
        self._heading.setFontWeight(QFont.Weight.Bold)
        self._heading.setFontPointSize(15)
        self._done = QTextCharFormat()
        self._done.setForeground(dim)
        self._done.setFontStrikeOut(True)
        self._link = QTextCharFormat()
        self._link.setForeground(QColor("#4C8DFF"))
        self._link.setFontUnderline(True)

    def highlightBlock(self, text: str) -> None:
        if text.startswith(("# ", "## ", "### ")):
            self.setFormat(0, len(text), self._heading)
            self.setFormat(0, text.index(" ") + 1, self._marker)
        task = _TASK_RE.match(text)
        if task:
            start = len(task[1])
            self.setFormat(start, 3, self._marker)
            if task[2] in "xX":
                self.setFormat(start + 4, len(text) - start - 4, self._done)
        for m in re.finditer(r"\*\*(.+?)\*\*", text):
            self.setFormat(m.start(), m.end() - m.start(), self._bold)
            self.setFormat(m.start(), 2, self._marker)
            self.setFormat(m.end() - 2, 2, self._marker)
        for m in re.finditer(r"(?<!\*)\*(?![\s*])(.+?)(?<![\s*])\*(?!\*)", text):
            self.setFormat(m.start(), m.end() - m.start(), self._italic)
            self.setFormat(m.start(), 1, self._marker)
            self.setFormat(m.end() - 1, 1, self._marker)
        for m in re.finditer(r"https?://[^\s<>\"]+", text):
            self.setFormat(m.start(), m.end() - m.start(), self._link)


class BodyEdit(QPlainTextEdit):
    """Plain text editor with Markdown helpers: list continuation and inline formatting."""

    def __init__(self):
        super().__init__()
        self.setTabChangesFocus(False)
        self._highlighter = MarkdownHighlighter(self.document())

    # ---- list continuation on Enter ----

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            cursor = self.textCursor()
            line = cursor.block().text()
            m = _LIST_RE.match(line)
            if m and not cursor.hasSelection():
                if not m[3].strip():  # empty item: end the list
                    self._replace_line("")
                else:
                    cursor.insertText("\n" + m[1] + ("[ ] " if m[2] else ""))
                    self.setTextCursor(cursor)
                return
        super().keyPressEvent(event)

    # ---- formatting actions ----

    def toggle_wrap(self, marker: str) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            if not cursor.hasSelection():
                return
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        text = self.toPlainText()
        n = len(marker)
        wrapped = (start >= n and text[start - n:start] == marker and text[end:end + n] == marker
                   and (n == 2 or not (start >= 2 and text[start - 2] == "*")))
        cursor.beginEditBlock()
        if wrapped:
            cursor.setPosition(end)
            cursor.setPosition(end + n, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.setPosition(start - n)
            cursor.setPosition(start, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        else:
            cursor.setPosition(end)
            cursor.insertText(marker)
            cursor.setPosition(start)
            cursor.insertText(marker)
        cursor.endEditBlock()
        # keep the content selected so the same button toggles it back
        inner_start = start - n if wrapped else start + n
        cursor.setPosition(inner_start)
        cursor.setPosition(inner_start + (end - start), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _replace_line(self, new_line: str) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(new_line)
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def cycle_heading(self) -> None:
        line = self.textCursor().block().text()
        if line.startswith("## "):
            self._replace_line(line[3:])
        elif line.startswith("# "):
            self._replace_line("## " + line[2:])
        else:
            self._replace_line("# " + line)

    def toggle_bullet(self) -> None:
        line = self.textCursor().block().text()
        self._replace_line(line[2:] if line.startswith("- ") else "- " + line)

    def cycle_checkbox(self) -> None:
        """plain line -> unchecked task -> checked task -> plain line."""
        line = self.textCursor().block().text()
        task = _TASK_RE.match(line)
        if task is None:
            self._replace_line("- [ ] " + (line[2:] if line.startswith("- ") else line))
        elif task[2] == " ":
            self._replace_line(f"{task[1]}[x] {task[3]}")
        else:
            self._replace_line(task[3])


class EditorPanel(QWidget):
    changed = Signal()
    delete_requested = Signal()
    keep_conflict_requested = Signal()

    def __init__(self):
        super().__init__()
        self._loading = False
        self._color = DEFAULT_COLOR
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 8)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_row = QHBoxLayout(self.banner)
        banner_row.addWidget(QLabel("Copie de conflit créée par la synchronisation."))
        banner_row.addStretch()
        keep = QPushButton("Garder celle-ci")
        keep.clicked.connect(self.keep_conflict_requested)
        remove = QPushButton("Supprimer")
        remove.clicked.connect(self.delete_requested)
        banner_row.addWidget(keep)
        banner_row.addWidget(remove)
        self.banner.hide()
        layout.addWidget(self.banner)

        head = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setObjectName("title")
        self.title.setPlaceholderText("Titre")
        self.pin = QToolButton()
        self.pin.setText("Épingler")
        self.pin.setCheckable(True)
        self.color_button = QToolButton()
        self.color_button.setText("Couleur")
        self.color_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.color_button)
        for color_id, label in COLORS.items():
            menu.addAction(label, lambda cid=color_id: self._pick_color(cid))
        self.color_button.setMenu(menu)
        head.addWidget(self.title, 1)
        head.addWidget(self.pin)
        head.addWidget(self.color_button)
        layout.addLayout(head)

        self.labels = QLineEdit()
        self.labels.setObjectName("labels")
        self.labels.setPlaceholderText("Libellés (séparés par des virgules)")
        layout.addWidget(self.labels)

        tools = QHBoxLayout()
        self.body = BodyEdit()
        for text, tip, fn in [
            ("G", "Gras (Ctrl+B)", lambda: self.body.toggle_wrap("**")),
            ("I", "Italique (Ctrl+I)", lambda: self.body.toggle_wrap("*")),
            ("T", "Titre", self.body.cycle_heading),
            ("•", "Puces", self.body.toggle_bullet),
            ("☑", "Liste à cocher (Ctrl+L)", self.body.cycle_checkbox),
        ]:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, f=fn: f())
            tools.addWidget(button)
        tools.addStretch()
        self.status = QLabel("")
        tools.addWidget(self.status)
        layout.addLayout(tools)
        layout.addWidget(self.body, 1)

        for shortcut, fn in [("Ctrl+B", lambda: self.body.toggle_wrap("**")),
                             ("Ctrl+I", lambda: self.body.toggle_wrap("*")),
                             ("Ctrl+L", self.body.cycle_checkbox)]:
            from PySide6.QtGui import QShortcut, QKeySequence
            QShortcut(QKeySequence(shortcut), self.body, activated=fn)

        self.title.textChanged.connect(self._edited)
        self.labels.textChanged.connect(self._edited)
        self.body.textChanged.connect(self._edited)
        self.pin.toggled.connect(self._edited)

    # ---- state ----

    def _edited(self, *_):
        if not self._loading:
            self.changed.emit()

    def _pick_color(self, color_id: str) -> None:
        self._color = color_id
        self._apply_color()
        self._edited()

    def _apply_color(self) -> None:
        bg, fg = theme.note_background(self._color), theme.note_foreground(self._color)
        if bg is None:
            self.setStyleSheet("")
            self.setAutoFillBackground(False)
            self.color_button.setText("Couleur")
        else:
            self.setStyleSheet(
                f"EditorPanel {{ background: {bg.name()}; }} "
                f"QLineEdit#title, QLineEdit#labels, QPlainTextEdit, QLabel {{ color: {fg.name()}; }}"
            )
            self.color_button.setText(f"Couleur : {COLORS.get(self._color, '')}")
        # QWidget subclasses need this to honour the stylesheet background
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def load(self, note: Note) -> None:
        self._loading = True
        self.title.setText(note.title)
        self.labels.setText(", ".join(note.labels))
        self.body.setPlainText(note.body)
        self.pin.setChecked(note.pinned)
        self._color = note.color if note.color in COLORS else DEFAULT_COLOR
        self._apply_color()
        self.banner.setVisible(note.conflict)
        self.status.setText("")
        self._loading = False

    def apply_to(self, note: Note) -> Note:
        labels = [x.strip() for x in self.labels.text().split(",") if x.strip()]
        return note.copy(title=self.title.text().strip(), body=self.body.toPlainText().strip("\n"),
                         color=self._color, pinned=self.pin.isChecked(), labels=labels)

    def focus_title(self) -> None:
        self.title.setFocus()

    def focus_body(self) -> None:
        self.body.setFocus()
        self.body.moveCursor(QTextCursor.MoveOperation.End)
