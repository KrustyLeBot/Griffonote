import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from griffonote_win.core import note as fmt
from griffonote_win.core.store import Store
from griffonote_win.services import updater
from griffonote_win.ui.main_window import MainWindow
from griffonote_win.ui.update_toast import UpdateToast


class FakeConfig:
    workdir = None
    geometry = None


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "latest", lambda: None)  # never touch the network
    w = MainWindow(FakeConfig(), Store(tmp_path))
    yield w
    w.save_timer.stop()
    w._update_timer.stop()


def files(tmp_path):
    return sorted(p.name for p in tmp_path.glob("*.md"))


def test_new_note_is_saved_with_a_fixed_file_name(window, tmp_path):
    window.new_note()
    window.editor.title.setText("Courses")
    window.editor.body.setPlainText("Lait\nPain")
    window.save_current()
    assert len(files(tmp_path)) == 1 and files(tmp_path)[0].startswith("courses-")
    name = files(tmp_path)[0]
    window.editor.title.setText("Autre titre")
    window.save_current()
    assert files(tmp_path) == [name]
    assert window.list.count() == 1


def test_empty_new_note_creates_no_file(window, tmp_path):
    window.new_note()
    window.save_current()
    window.new_note(checklist=True)
    window.save_current()
    assert files(tmp_path) == []


def test_edit_color_pin_and_labels_land_in_the_file(window, tmp_path):
    window.new_note()
    window.editor.title.setText("Idées")
    window.editor.pin.setChecked(True)
    window.editor.labels.setText("perso, dev")
    window.editor._pick_color("yellow")
    window.save_current()
    note = fmt.parse("x.md", (tmp_path / files(tmp_path)[0]).read_text(), 0)
    assert (note.pinned, note.color, note.labels) == (True, "yellow", ["perso", "dev"])


def test_delete_asks_then_removes_the_file(window, tmp_path, monkeypatch):
    window.new_note()
    window.editor.title.setText("Bye")
    window.save_current()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window.delete_current()
    assert len(files(tmp_path)) == 1
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.delete_current()
    assert files(tmp_path) == [] and window.list.count() == 0


def test_external_change_reloads_when_there_is_no_local_edit(window, tmp_path):
    window.new_note()
    window.editor.title.setText("Partagée")
    window.editor.body.setPlainText("v1")
    window.save_current()
    path = tmp_path / files(tmp_path)[0]
    path.write_text(path.read_text().replace("v1", "v2 depuis le PC"))
    window._on_disk_changed()
    assert window.editor.body.toPlainText() == "v2 depuis le PC"


def test_external_note_appears_in_the_list(window, tmp_path):
    (tmp_path / "du-pc.md").write_text("Bonjour")
    window._on_disk_changed()
    assert window.list.count() == 1


def test_search_and_label_filter(window, tmp_path):
    for title, labels in [("Alpha", "x"), ("Beta", "y")]:
        window.new_note()
        window.editor.title.setText(title)
        window.editor.labels.setText(labels)
        window.save_current()
    assert window.list.count() == 2
    window.search.setText("alp")
    assert window.list.count() == 1
    window.search.setText("")
    window.label_filter.setCurrentIndex(window.label_filter.findText("y"))
    assert window.list.count() == 1


def test_checklist_helpers_and_list_continuation(window):
    body = window.editor.body
    body.setPlainText("Lait")
    body.cycle_checkbox()
    assert body.toPlainText() == "- [ ] Lait"
    body.cycle_checkbox()
    assert body.toPlainText() == "- [x] Lait"
    body.cycle_checkbox()
    assert body.toPlainText() == "Lait"
    body.setPlainText("Texte")
    body.selectAll()
    body.toggle_wrap("**")
    assert body.toPlainText() == "**Texte**"
    assert body.textCursor().selectedText() == "Texte"
    body.toggle_wrap("**")
    assert body.toPlainText() == "Texte"


def test_update_toast_shows_when_a_newer_build_exists(window, monkeypatch):
    monkeypatch.setattr(updater._version, "BUILD", 1)
    window.show()
    window.toast = UpdateToast(window, updater.Release(2, "http://x/g.exe"))
    window.toast.place()
    window.toast.show()
    assert window.toast.isVisible()
    assert window.toast.x() > window.width() // 2
