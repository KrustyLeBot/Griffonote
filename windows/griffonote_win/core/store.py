"""The notes folder is the source of truth; this is a thin cache over it."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from . import atomic
from . import fit, gpx
from . import note as fmt
from .activity import ActivityInfo
from .analysis import analyze
from .note import Note
from .track import Sport, Track

ACTIVITIES_DIR = "activities"


# Above this, a file is refused: it is synced to every device (same limit as the Android app).
MAX_ATTACHMENT = 50_000_000


def now_ms() -> int:
    return int(time.time() * 1000)


def default_title(sport: Sport, start: int, name: str | None = None) -> str:
    if name and name.strip():
        return name.strip()
    from datetime import datetime
    months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    d = datetime.fromtimestamp(start / 1000)
    return f"{sport.label.split(' (')[0]} du {d.day} {months[d.month - 1]} {d.year}"


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._cache: dict[str, tuple[int, Note]] = {}  # path -> (mtime_ns, note)

    # ---- reading ----

    def scan(self) -> list[Note]:
        """Reads only the files whose modification time changed."""
        notes: list[Note] = []
        seen: set[str] = set()
        try:
            entries = list(os.scandir(self.root))
        except OSError:
            entries = []
        for entry in entries:
            name = entry.name
            if not entry.is_file() or not name.endswith(".md") or name.startswith("."):
                continue
            seen.add(name)
            mtime = entry.stat().st_mtime_ns
            cached = self._cache.get(name)
            if cached and cached[0] == mtime:
                notes.append(cached[1])
                continue
            try:
                text = (self.root / name).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            note = fmt.parse(name, text, mtime // 1_000_000)
            self._cache[name] = (mtime, note)
            notes.append(note)
        for stale in set(self._cache) - seen:
            del self._cache[stale]
        return notes

    def scan_activities(self) -> list[Note]:
        """The notes of the "Activités" folder (activities/*.md), kept out of the regular list."""
        notes: list[Note] = []
        seen: set[str] = set()
        try:
            entries = list(os.scandir(self.root / ACTIVITIES_DIR))
        except OSError:
            entries = []
        for entry in entries:
            if not entry.is_file() or not entry.name.endswith(".md") or entry.name.startswith("."):
                continue
            path = f"{ACTIVITIES_DIR}/{entry.name}"
            seen.add(path)
            mtime = entry.stat().st_mtime_ns
            cached = self._cache.get(path)
            if cached and cached[0] == mtime:
                notes.append(cached[1])
                continue
            try:
                text = (self.root / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            note = fmt.parse(path, text, mtime // 1_000_000)
            self._cache[path] = (mtime, note)
            notes.append(note)
        for stale in [k for k in self._cache if k.startswith(f"{ACTIVITIES_DIR}/")] :
            if stale not in seen:
                del self._cache[stale]
        return notes

    def read_raw(self, path: str) -> str | None:
        try:
            return (self.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def snapshot(self):
        """Cheap fingerprint of the folder (names, times, sizes): tells whether another device changed it.
        None when the folder cannot be read right now (share offline)."""
        try:
            files = sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size)
                           for e in os.scandir(self.root) if e.is_file() and not e.name.startswith("."))
        except OSError:
            return None
        try:
            acts = sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size)
                          for e in os.scandir(self.root / ACTIVITIES_DIR) if e.is_file() and not e.name.startswith("."))
        except OSError:
            acts = []
        return tuple(files), tuple(acts)

    def labels(self) -> list[str]:
        return sorted({lbl for n in self.scan() for lbl in n.labels}, key=fmt.fold)

    # ---- writing ----

    def _write(self, path: str, text: str) -> None:
        atomic.write_text(self.root / path, text)

    def save(self, note: Note) -> Note:
        """Writes the note; the file is created (and its name fixed) on the first save."""
        if not note.path:
            taken = {n.id for n in self.scan()} | {n.id for n in self.scan_activities()}
            note_id = note.id
            while not note_id or note_id in taken:
                note_id = fmt.generate_id()
            note = note.copy(id=note_id, path=fmt.file_name_for(note.title, note_id))
        note = note.copy(has_id=True)
        self._write(note.path, fmt.serialize(note))
        mtime = (self.root / note.path).stat().st_mtime_ns
        self._cache[note.path] = (mtime, note)
        return note

    def pdf_path(self, note: Note) -> Path | None:
        """Absolute path of the note's scanned PDF, if it has one."""
        return self.root / note.pdf if note.pdf else None

    def file_path(self, relative: str) -> Path:
        return self.root / relative

    def add_attachment(self, source: Path) -> str:
        """Copies the file into attachments/ and returns its path relative to the notes folder."""
        size = source.stat().st_size
        if size > MAX_ATTACHMENT:
            raise OSError(f"{source.name} dépasse {MAX_ATTACHMENT // 1_000_000} Mo")
        relative = fmt.attachment_path(source.name)
        while self.file_path(relative).exists():
            relative = fmt.attachment_path(source.name)
        atomic.write_bytes(self.file_path(relative), source.read_bytes())
        return relative

    # ---- activities ----

    def read_track(self, info: ActivityInfo) -> Track:
        """The FIT/GPX file of an activity."""
        if not info.file:
            raise OSError("Pas de tracé")
        data = self.file_path(info.file).read_bytes()
        return fit.read(data) if fit.looks_like_fit(data) else gpx.read(data.decode("utf-8", "replace"))

    def import_activity(self, source: Path, title: str | None, sport: Sport | None) -> Note:
        """Reads a FIT or GPX file, copies it to attachments/ and creates the activity note."""
        if source.stat().st_size > MAX_ATTACHMENT:
            raise OSError(f"{source.name} dépasse {MAX_ATTACHMENT // 1_000_000} Mo")
        data = source.read_bytes()
        if fit.looks_like_fit(data):
            track, ext = fit.read(data), "fit"
        else:
            track, ext = gpx.read(data.decode("utf-8", "replace")), "gpx"
        if not track.points and track.session_distance is None:
            raise fit.FitError("Aucune position dans ce fichier")
        sport = sport or (Sport.from_fit(track.fit_sport) if ext == "fit" else Sport.WALK)
        start = track.start_time or now_ms()
        title = (title or "").strip() or default_title(sport, start, track.name)
        taken = {n.id for n in self.scan()} | {n.id for n in self.scan_activities()}
        note_id = fmt.generate_id()
        while note_id in taken:
            note_id = fmt.generate_id()
        relative = f"attachments/{fmt.slug(title)}-{note_id}.{ext}"
        atomic.write_bytes(self.file_path(relative), data)
        info = ActivityInfo.from_analysis(sport, analyze(track, sport), track, relative)
        now = now_ms()
        return self.save(Note(path=f"{ACTIVITIES_DIR}/{fmt.file_name_for(title, note_id)}", id=note_id, title=title,
                              created=now, updated=now, activity=info, attachments=[relative]))

    def update_activity(self, note: Note, title: str, description: str, sport: Sport) -> Note:
        info = note.activity
        if info is not None and info.sport != sport:
            if info.file:
                track = self.read_track(info)
                info = ActivityInfo.from_analysis(sport, analyze(track, sport), track, info.file)
            else:
                info = ActivityInfo(**{**info.__dict__, "sport": sport})
        return self.save(note.copy(title=title.strip() or note.title, body=description.strip(), activity=info, updated=now_ms()))

    def delete(self, note: Note) -> None:
        for path in (self.root / note.path, self.pdf_path(note), *(self.file_path(a) for a in note.attachments)):
            try:
                if path is not None:
                    path.unlink()
            except FileNotFoundError:
                pass
        self._cache.pop(note.path, None)

    def keep_conflict_copy(self, copy: Note) -> Note:
        """This copy replaces the original (same id, no "conflict" in its name)."""
        original = next((n for n in self.scan() if n.id == copy.id and not n.conflict and n.path != copy.path), None)
        target = original.path if original else re.sub(r"(?i)[ ._-]*conflict[^.]*", "", copy.path)
        kept = copy.copy(path=target, conflict=False, updated=now_ms())
        self._write(target, fmt.serialize(kept))
        if target != copy.path:
            self.delete(copy)
        self._cache.pop(target, None)
        return kept
