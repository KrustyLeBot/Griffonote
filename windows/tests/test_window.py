import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from griffonote_win.core import note as fmt
from griffonote_win.core.store import Store, now_ms
from griffonote_win.services import updater
from griffonote_win.ui import theme
from griffonote_win.ui.main_window import MainWindow
from griffonote_win.ui.update_toast import UpdateToast


class FakeConfig:
    workdir = None
    geometry = None
    grid = True
    theme = "light"


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    theme.apply_theme(application, "light")
    return application


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "latest", lambda: None)  # never touch the network
    w = MainWindow(FakeConfig(), Store(tmp_path))
    w.resize(1000, 700)
    w.show()
    yield w
    w.editor.save_timer.stop()
    w._update_timer.stop()


def files(tmp_path):
    return sorted(p.name for p in tmp_path.glob("*.md"))


def read(tmp_path, name=None):
    path = tmp_path / (name or files(tmp_path)[0])
    return fmt.parse(path.name, path.read_text(encoding="utf-8"), 0)


def add(store, title, body="", **kw):
    return store.save(fmt.Note(path="", id=fmt.generate_id(), title=title, body=body,
                               created=now_ms(), updated=now_ms(), **kw))


def test_new_note_is_saved_with_a_fixed_file_name(window, tmp_path):
    window.new_note()
    ed = window.editor
    ed.title.setText("Courses")
    ed.save()
    name = files(tmp_path)[0]
    assert name.startswith("courses-")
    ed.title.setText("Autre titre")
    ed.save()
    assert files(tmp_path) == [name]


def test_empty_new_notes_create_no_file(window, tmp_path):
    window.new_note()
    window.editor.save()
    window.new_note(checklist=True)
    window.editor.save()
    window.close_editor()
    assert files(tmp_path) == []


def test_checklist_items_check_fold_and_reorder(window, tmp_path):
    window.new_note(checklist=True)
    ed = window.editor
    ed.title.setText("Liste")
    ed.checklist.set_items([fmt.CheckItem("Lait"), fmt.CheckItem("Pain"), fmt.CheckItem("Oeufs")])
    ed._edited()
    # tick "Lait": it moves to the folded section
    first = ed.checklist._rows(ed.checklist.open_box)[0]
    first.box.setChecked(True)
    assert [i.text for i in ed.checklist.items()] == ["Pain", "Oeufs", "Lait"]
    assert ed.checklist.fold_button.text().strip() == "1 élément coché"
    # reorder through the drag logic
    rows = ed.checklist._rows(ed.checklist.open_box)
    ed.checklist._drag_start(rows[1])
    y = rows[0].mapToGlobal(rows[0].rect().topLeft()).y() - 5
    ed.checklist._drag_move(rows[1], y)
    ed.checklist._drag_end(rows[1])
    assert [i.text for i in ed.checklist.items()] == ["Oeufs", "Pain", "Lait"]
    ed.save()
    body = read(tmp_path).body
    assert body == "- [ ] Oeufs\n- [ ] Pain\n- [x] Lait"


def test_enter_adds_an_item_and_backspace_on_empty_removes_it(window):
    window.new_note(checklist=True)
    cl = window.editor.checklist
    cl.set_items([fmt.CheckItem("A")])
    row = cl._rows(cl.open_box)[0]
    row.enter_pressed.emit(row)
    assert cl.count() == 2
    new = cl._rows(cl.open_box)[1]
    QTest.keyClick(new.edit, Qt.Key.Key_Backspace)
    assert cl.count() == 1


def test_wysiwyg_bold_and_bullets_are_stored_as_markdown(window, tmp_path):
    window.new_note()
    ed = window.editor
    ed.title.setText("Format")
    ed.body.set_markdown("Bonjour monde")
    cursor = ed.body.textCursor()
    cursor.setPosition(8)
    cursor.setPosition(13, cursor.MoveMode.KeepAnchor)
    ed.body.setTextCursor(cursor)
    ed.body.toggle_bold()
    ed.body.moveCursor(ed.body.textCursor().MoveOperation.End)
    ed.body.toggle_bullet()
    assert ed.body.markdown() == "- Bonjour **monde**"
    ed._edited()
    ed.save()
    assert read(tmp_path).body == "- Bonjour **monde**"
    # reopening shows styled text, not markdown symbols
    window.close_editor()
    window.open_note(window.notes[0])
    assert ed.body.document().toPlainText() == "Bonjour monde"


def test_heading_ends_at_enter(window):
    window.new_note()
    body = window.editor.body
    body.set_markdown("Titre")
    body.cycle_heading()
    assert body.markdown() == "# Titre"
    QTest.keyClick(body, Qt.Key.Key_Return)
    QTest.keyClicks(body, "suite")
    assert body.markdown() == "# Titre\nsuite"


def test_color_pin_and_labels_land_in_the_file(window, tmp_path):
    window.new_note()
    ed = window.editor
    ed.title.setText("Idées")
    ed.pin_button.setChecked(True)
    ed._color = "yellow"
    ed.current = ed.current.copy(labels=["perso", "dev"])
    ed._edited()
    ed.save()
    note = read(tmp_path)
    assert (note.pinned, note.color, note.labels) == (True, "yellow", ["perso", "dev"])


def test_delete_removes_the_file_and_undo_restores_it(window, tmp_path):
    note = add(window.store, "Bye", "texte")
    window.refresh()
    window.open_note(note)
    window.editor._request_delete()
    assert files(tmp_path) == [] and window.stack.currentWidget() is window.list_screen
    assert window.snack_button.isVisibleTo(window.snack)
    window.snack_button.click()
    assert files(tmp_path) == [note.path]
    assert len(window.list_screen.visible_notes()) == 1


def test_external_change_reloads_when_there_is_no_local_edit(window, tmp_path):
    note = add(window.store, "Partagée", "v1")
    window.refresh()
    window.open_note(note)
    path = tmp_path / note.path
    path.write_text(path.read_text().replace("v1", "v2 depuis le PC"))
    window._on_disk_changed()
    assert window.editor.body.document().toPlainText() == "v2 depuis le PC"


def test_external_note_appears_in_the_list(window, tmp_path):
    (tmp_path / "du-pc.md").write_text("Bonjour")
    window._on_disk_changed()
    assert len(window.list_screen.visible_notes()) == 1


def test_search_label_filter_and_pinned_sections(window):
    add(window.store, "Alpha", "x", labels=["a"], pinned=True)
    add(window.store, "Beta", "y", labels=["b"])
    window.refresh()
    ls = window.list_screen
    assert [n.title for n in ls.visible_notes()] == ["Alpha", "Beta"]  # pinned first
    ls.search.setText("bet")
    assert [n.title for n in ls.visible_notes()] == ["Beta"]
    ls.search.setText("")
    ls._pick_label("a")
    assert [n.title for n in ls.visible_notes()] == ["Alpha"]
    assert any(kind == "header" for kind, _ in ls._items)


def test_conflict_copy_can_replace_the_original(window, tmp_path):
    original = add(window.store, "Courses", "ancien")
    (tmp_path / f"courses-{original.id}.conflict-1.md").write_text(fmt.serialize(original.copy(body="nouveau")))
    window.refresh()
    copy = next(n for n in window.notes if n.conflict)
    window.open_note(copy)
    window.editor.keep_conflict()
    assert files(tmp_path) == [original.path]
    assert read(tmp_path).body == "nouveau"


def test_theme_switch_and_settings_page(window):
    window.show_settings()
    window.settings.theme_buttons["dark"].click()
    assert theme.is_dark()
    window.settings.theme_buttons["light"].click()
    assert not theme.is_dark()
    window.settings.list_button.click()
    assert window.list_screen.grid is False


def test_update_toast_shows_when_a_newer_build_exists(window, monkeypatch):
    monkeypatch.setattr(updater._version, "BUILD", 1)
    window.toast = UpdateToast(window, updater.Release(2, "http://x/g.exe"))
    window.toast.place()
    window.toast.show()
    assert window.toast.isVisible()
    assert window.toast.x() > window.width() // 2
