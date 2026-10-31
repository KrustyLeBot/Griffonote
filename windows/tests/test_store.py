import pytest
import time

from griffonote_win.core import note as fmt
from griffonote_win.core.store import Store, now_ms


def make(store, title, body=""):
    return store.save(fmt.Note(path="", id=fmt.generate_id(), title=title, body=body, created=now_ms(), updated=now_ms()))


def test_first_save_fixes_the_file_name_and_never_renames(tmp_path):
    store = Store(tmp_path)
    n = make(store, "Courses")
    assert n.path == f"courses-{n.id}.md"
    renamed = store.save(n.copy(title="Autre titre"))
    assert renamed.path == n.path
    assert [p.name for p in tmp_path.glob("*.md")] == [n.path]


def test_scan_reads_notes_and_ignores_temp_files(tmp_path):
    store = Store(tmp_path)
    make(store, "Une", "texte")
    (tmp_path / ".x.md.tmp").write_text("junk")
    (tmp_path / "autre.txt").write_text("junk")
    (tmp_path / "sans-frontmatter.md").write_text("Bonjour")
    titles = sorted(n.title for n in store.scan())
    assert titles == ["Une", "sans frontmatter"]


def test_scan_picks_up_external_edits(tmp_path):
    store = Store(tmp_path)
    n = make(store, "Note", "v1")
    time.sleep(0.02)
    fresh = (tmp_path / n.path).read_text().replace("v1", "v2")
    (tmp_path / n.path).write_text(fresh)
    assert store.scan()[0].body == "v2"


def test_delete_removes_the_file(tmp_path):
    store = Store(tmp_path)
    n = make(store, "A supprimer")
    store.delete(n)
    assert store.scan() == []
    store.delete(n)  # idempotent


def test_keep_conflict_copy_replaces_the_original(tmp_path):
    store = Store(tmp_path)
    original = make(store, "Courses", "ancien")
    copy_text = fmt.serialize(original.copy(body="nouveau"))
    (tmp_path / f"courses-{original.id}.conflict-1.md").write_text(copy_text)
    copy = next(n for n in store.scan() if n.conflict)
    kept = store.keep_conflict_copy(copy)
    assert kept.path == original.path
    notes = store.scan()
    assert len(notes) == 1 and notes[0].body == "nouveau" and not notes[0].conflict


def test_deleting_a_scan_note_deletes_its_pdf(tmp_path):
    from griffonote_win.core.note import Note
    from griffonote_win.core.store import Store, now_ms
    store = Store(tmp_path)
    (tmp_path / "attachments").mkdir()
    pdf = tmp_path / "attachments" / "scan-abc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    note = store.save(Note(path="", id="abc123", title="Scan", created=now_ms(), updated=now_ms(), pdf="attachments/scan-abc.pdf"))
    assert store.pdf_path(note) == pdf
    store.delete(note)
    assert not pdf.exists() and not (tmp_path / note.path).exists()


def test_atomic_write_leaves_no_temporary(tmp_path):
    from griffonote_win.core import atomic

    target = tmp_path / "sub" / "a.md"
    atomic.write_text(target, "one")
    atomic.write_text(target, "two")
    assert target.read_text(encoding="utf-8") == "two"
    assert [p.name for p in target.parent.iterdir()] == ["a.md"]
    assert atomic.is_temp(atomic.temp_name("a.md"))
    assert atomic.temp_name("a.md").startswith(".a.md.synctmp-")


def test_attachments_are_copied_in_and_deleted_with_the_note(tmp_path):
    store = Store(tmp_path / "notes")
    source = tmp_path / "Photo vacances.JPG"
    source.write_bytes(b"\xff\xd8 image")
    rel = store.add_attachment(source)
    assert rel.startswith("attachments/photo-vacances-") and rel.endswith(".jpg")
    assert store.file_path(rel).read_bytes() == b"\xff\xd8 image"
    note = store.save(fmt.Note(path="", id="abc123", title="Vacances", created=now_ms(), updated=now_ms(), attachments=[rel]))
    assert store.scan()[0].attachments == [rel]
    store.delete(note)
    assert not store.file_path(rel).exists()
    assert source.exists()


def test_importing_a_fit_file_creates_an_activity_in_its_own_folder(tmp_path):
    from pathlib import Path
    from griffonote_win.core.store import Store
    store = Store(tmp_path)
    note = store.import_activity(Path(__file__).parent / "data" / "synthetic.fit", None, None)
    assert note.path.startswith("activities/")
    assert (tmp_path / note.path).is_file()
    assert note.activity.file and (tmp_path / note.activity.file).is_file()
    assert note.attachments == [note.activity.file]
    assert note.activity.sport.key == "bike"
    assert note.activity.distance == pytest.approx(267.0, abs=0.1)  # the watch's own total is kept when close to ours
    # not in the regular list, but in the activities folder
    assert store.scan() == []
    assert [n.path for n in store.scan_activities()] == [note.path]
    # the track can be read back and the note deleted with its file
    assert len(store.read_track(note.activity).points) == 90
    store.delete(note)
    assert store.scan_activities() == []
    assert not (tmp_path / note.activity.file).exists()


def test_importing_a_gpx_file(tmp_path):
    from griffonote_win.core.store import Store
    gpx = tmp_path / "ride.gpx"
    pts = "".join(f'<trkpt lat="{45 + i * 3 / 111320:.7f}" lon="6.0"><ele>{1000 + i}</ele><time>2024-01-01T10:{i // 60:02d}:{i % 60:02d}Z</time></trkpt>'
                  for i in range(120))
    gpx.write_text(f'<?xml version="1.0"?><gpx><trk><name>Sortie test</name><trkseg>{pts}</trkseg></trk></gpx>', encoding="utf-8")
    store = Store(tmp_path / "notes")
    note = store.import_activity(gpx, None, None)
    assert note.title == "Sortie test"
    assert note.activity.file.endswith(".gpx")
    assert note.activity.ascent >= 100


def test_reimporting_the_same_recording_replaces_the_activity_and_keeps_the_photos(tmp_path):
    from pathlib import Path
    from griffonote_win.core.store import Store
    from griffonote_win.core.track import Sport
    store = Store(tmp_path)
    source = Path(__file__).parent / "data" / "synthetic.fit"
    first = store.import_activity(source, "Sortie du matin", Sport.GPS)
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"\xff\xd8\xff")
    relative = store.add_attachment(photo)
    first = store.save(first.copy(attachments=first.attachments + [relative], body="Belle sortie"))
    found = store.find_activity(store.read_source(source)[0].start_time)
    assert found is not None and found.id == first.id
    again = store.import_activity(source, None, Sport.EBIKE, replace=found)
    assert again.id == first.id and again.path == first.path
    assert again.title == "Sortie du matin" and again.body == "Belle sortie"
    assert again.activity.sport == Sport.EBIKE
    assert relative in again.attachments and again.activity.file in again.attachments
    assert len(store.scan_activities()) == 1
    assert not (tmp_path / first.activity.file).exists() or first.activity.file == again.activity.file
