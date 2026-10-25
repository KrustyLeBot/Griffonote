from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidgetItem, QMainWindow, QMessageBox,
                               QSizePolicy, QSplitter, QStackedWidget, QToolBar, QVBoxLayout, QWidget)

from ..config import Config
from ..core import note as fmt
from ..core.note import Note
from ..core.store import Store, now_ms
from ..services import updater
from ..services.async_util import run_async
from .editor import EditorPanel
from .note_list import NOTE_ROLE, NoteList
from .update_toast import UpdateToast

ALL_LABELS = "Tous les libellés"


def ask_workdir(parent, first_run: bool, start: Path | None = None) -> Path | None:
    """Asks for the notes folder (the same one the phone syncs); returns None if the user cancels."""
    if first_run:
        QMessageBox.information(
            parent, "Griffonote",
            "Choisis le dossier qui contient tes notes (celui synchronisé avec ton téléphone).\n"
            "Si le dossier est vide, Griffonote y créera tes nouvelles notes.",
        )
    chosen = QFileDialog.getExistingDirectory(parent, "Dossier des notes", str(start or Path.home()))
    return Path(chosen) if chosen else None


class MainWindow(QMainWindow):
    def __init__(self, config: Config, store: Store):
        super().__init__()
        self.config = config
        self.store = store
        self.current: Note | None = None  # last saved/loaded version of the open note ("" path = not saved yet)
        self.loaded_raw: str | None = None
        self.dirty = False
        self.notes: list[Note] = []
        self.toast: UpdateToast | None = None
        self._cleanup_tries = 0
        self._filling = False
        self.resize(1100, 720)

        # ---- left: search, label filter, list ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Rechercher dans vos notes")
        self.search.setClearButtonEnabled(True)
        self.label_filter = QComboBox()
        self.list = NoteList()
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.label_filter)
        left_layout.addWidget(self.list, 1)

        # ---- right: editor or placeholder ----
        self.editor = EditorPanel()
        self.placeholder = QLabel("Sélectionne une note ou crée-en une nouvelle (Ctrl+N).")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.editor)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 760])
        self.setCentralWidget(splitter)

        self._build_actions()

        # ---- wiring ----
        self.search.textChanged.connect(lambda _: self.refresh())
        self.label_filter.currentIndexChanged.connect(lambda _: self.refresh())
        self.list.currentItemChanged.connect(self._on_select)
        self.editor.changed.connect(self._on_edited)
        self.editor.delete_requested.connect(self.delete_current)
        self.editor.keep_conflict_requested.connect(self.keep_conflict)

        self.save_timer = QTimer(self, singleShot=True, interval=700)
        self.save_timer.timeout.connect(self.save_current)

        # The sync tool can drop files in the folder at any time: debounce, then rescan.
        self.watcher = QFileSystemWatcher(self)
        self.watch_timer = QTimer(self, singleShot=True, interval=800)
        self.watch_timer.timeout.connect(self._on_disk_changed)
        self.watcher.directoryChanged.connect(lambda _: self.watch_timer.start())
        self.watcher.fileChanged.connect(lambda _: self.watch_timer.start())

        # ---- self-update ----
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._cleanup_old_exe)
        if not updater.cleanup_previous():
            self._cleanup_timer.start(2000)  # retry every 2 s ...
        QTimer.singleShot(5000, self.check_updates)  # first check shortly after the start
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self.check_updates)
        self._update_timer.start(6 * 3600 * 1000)  # ... then every 6 hours

        self.set_store(store)
        geometry = config.geometry
        if geometry:
            self.restoreGeometry(geometry)

    # ---- actions ----

    def _build_actions(self) -> None:
        bar = QToolBar("Principal")
        bar.setMovable(False)
        self.addToolBar(bar)

        def action(text: str, shortcut: str | None, slot) -> QAction:
            act = QAction(text, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(lambda _=False: slot())
            return act

        self.new_action = action("Nouvelle note", "Ctrl+N", self.new_note)
        self.new_list_action = action("Nouvelle liste", "Ctrl+Shift+N", lambda: self.new_note(checklist=True))
        self.delete_action = action("Supprimer", "Ctrl+Shift+Delete", self.delete_current)
        bar.addAction(self.new_action)
        bar.addAction(self.new_list_action)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        bar.addAction(self.delete_action)  # far right, like on the phone

        menu = self.menuBar().addMenu("Fichier")
        menu.addAction(action("Dossier de notes…", None, self.choose_workdir))
        menu.addAction(action("Rechercher une mise à jour", None, lambda: self.check_updates(manual=True)))
        menu.addSeparator()
        menu.addAction(action("Quitter", "Ctrl+Q", self.close))

    # ---- store / list ----

    def set_store(self, store: Store) -> None:
        self.save_current()
        self.store = store
        self.current, self.loaded_raw, self.dirty = None, None, False
        self.stack.setCurrentWidget(self.placeholder)
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self._arm_watcher()
        self.setWindowTitle(f"Griffonote — {store.root}")
        self.refresh()

    def _arm_watcher(self) -> None:
        # Re-add the paths after every event: an atomically replaced file loses its watch.
        root = str(self.store.root)
        if root not in self.watcher.directories():
            self.watcher.addPath(root)

    def choose_workdir(self) -> None:
        path = ask_workdir(self, first_run=False, start=self.store.root)
        if path is not None:
            self.config.workdir = path
            self.set_store(Store(path))

    def _visible(self) -> list[Note]:
        query = fmt.fold(self.search.text().strip())
        label = self.label_filter.currentText()
        out = []
        for n in self.notes:
            if label and label != ALL_LABELS and label not in n.labels:
                continue
            if query and not (query in fmt.fold(n.title) or query in fmt.fold(n.body)
                              or any(query in fmt.fold(x) for x in n.labels)):
                continue
            out.append(n)
        out.sort(key=lambda n: (not n.pinned, -n.updated))
        return out

    def refresh(self, select_path: str | None = None) -> None:
        self.notes = self.store.scan()
        wanted = select_path or (self.current.path if self.current else "")
        self._filling = True
        try:
            labels = sorted({x for n in self.notes for x in n.labels}, key=fmt.fold)
            selected_label = self.label_filter.currentText()
            self.label_filter.blockSignals(True)
            self.label_filter.clear()
            self.label_filter.addItem(ALL_LABELS)
            self.label_filter.addItems(labels)
            index = self.label_filter.findText(selected_label)
            self.label_filter.setCurrentIndex(max(index, 0))
            self.label_filter.blockSignals(False)

            self.list.clear()
            for note in self._visible():
                item = QListWidgetItem()
                item.setData(NOTE_ROLE, note)
                self.list.addItem(item)
                if wanted and note.path == wanted:
                    self.list.setCurrentItem(item)
        finally:
            self._filling = False

    # ---- editing ----

    def _on_select(self, item, _previous) -> None:
        if self._filling or item is None:
            return
        self.save_current()
        self.open_note(item.data(NOTE_ROLE))

    def open_note(self, note: Note) -> None:
        self.current = note
        self.loaded_raw = self.store.read_raw(note.path)
        self.editor.load(note)
        self.dirty = False
        self.stack.setCurrentWidget(self.editor)

    def new_note(self, checklist: bool = False) -> None:
        self.save_current()
        note = Note(path="", id=fmt.generate_id(), created=now_ms(), updated=now_ms(),
                    body="- [ ] " if checklist else "")
        self.current, self.loaded_raw, self.dirty = note, None, False
        self._filling = True
        self.list.clearSelection()
        self.list.setCurrentItem(None)
        self._filling = False
        self.editor.load(note)
        self.stack.setCurrentWidget(self.editor)
        if checklist:
            self.editor.focus_body()
        else:
            self.editor.focus_title()

    def _on_edited(self) -> None:
        if self.current is None:
            return
        self.dirty = True
        self.editor.status.setText("Modifications en cours…")
        self.save_timer.start()

    @staticmethod
    def _is_blank(note: Note) -> bool:
        return not note.title and note.body.strip() in ("", "- [ ]")

    def save_current(self) -> None:
        self.save_timer.stop()
        if self.current is None or not self.dirty:
            return
        edited = self.editor.apply_to(self.current)
        if not edited.path and self._is_blank(edited):
            return  # nothing worth a file yet
        edited = edited.copy(updated=now_ms())
        try:
            saved = self.store.save(edited)
        except OSError as exc:
            self.editor.status.setText(f"Échec de l'enregistrement : {exc}")
            return
        self.current = saved
        self.loaded_raw = self.store.read_raw(saved.path)
        self.dirty = False
        self.editor.status.setText("Enregistré")
        self.refresh(select_path=saved.path)

    def delete_current(self) -> None:
        if self.current is None:
            return
        if self.current.path:
            answer = QMessageBox.question(
                self, "Supprimer la note", "Supprimer définitivement cette note ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.store.delete(self.current)
        self.save_timer.stop()
        self.current, self.loaded_raw, self.dirty = None, None, False
        self.stack.setCurrentWidget(self.placeholder)
        self.refresh()

    def keep_conflict(self) -> None:
        if self.current is None or not self.current.conflict:
            return
        self.save_current()
        kept = self.store.keep_conflict_copy(self.current)
        self.open_note(kept)
        self.refresh(select_path=kept.path)

    # ---- external changes (sync, edits on another tool) ----

    def _on_disk_changed(self) -> None:
        self._arm_watcher()
        self.refresh()
        if self.current is None or not self.current.path:
            return
        raw = self.store.read_raw(self.current.path)
        if raw == self.loaded_raw:
            return
        if raw is None:  # deleted elsewhere
            if not self.dirty:
                self.current, self.loaded_raw = None, None
                self.stack.setCurrentWidget(self.placeholder)
            return
        disk = next((n for n in self.notes if n.path == self.current.path), None)
        if disk is None:
            return
        if not self.dirty:
            self.open_note(disk)
            return
        box = QMessageBox(self)
        box.setWindowTitle("Note modifiée ailleurs")
        box.setText("Ce fichier a changé sur le disque (synchronisation ou autre éditeur) pendant que tu le modifiais.")
        mine = box.addButton("Garder ma version", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Recharger", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is mine:
            self.loaded_raw = raw
            self.current = self.current.copy(extra=disk.extra)
            self.save_current()
        else:
            self.open_note(disk)

    # ---- self-update ----

    def _cleanup_old_exe(self) -> None:
        self._cleanup_tries += 1
        if updater.cleanup_previous() or self._cleanup_tries >= 60:  # ... for 2 minutes
            self._cleanup_timer.stop()

    def check_updates(self, manual: bool = False) -> None:
        def done(result):
            if isinstance(result, Exception):
                if manual:
                    QMessageBox.warning(self, "Mise à jour", f"Vérification impossible : {result}")
                return
            if result is None or not updater.is_newer(result):
                if manual:
                    QMessageBox.information(self, "Mise à jour",
                                            f"Tu as la dernière version (build {updater.current_build()}).")
                return
            if self.toast is None or self.toast.release.build != result.build:
                self.toast = UpdateToast(self, result)
            self.toast.place()
            self.toast.show()

        run_async(updater.latest, done, done)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.toast is not None and self.toast.isVisible():
            self.toast.place()  # stays pinned to the top-right corner

    def closeEvent(self, event) -> None:
        self.save_current()
        self.config.geometry = self.saveGeometry()
        super().closeEvent(event)
