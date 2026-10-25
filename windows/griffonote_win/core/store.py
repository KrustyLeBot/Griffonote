"""The notes folder is the source of truth; this is a thin cache over it."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from . import note as fmt
from .note import Note


def now_ms() -> int:
    return int(time.time() * 1000)


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

    def read_raw(self, path: str) -> str | None:
        try:
            return (self.root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def labels(self) -> list[str]:
        return sorted({lbl for n in self.scan() for lbl in n.labels}, key=fmt.fold)

    # ---- writing ----

    def _write(self, path: str, text: str) -> None:
        """Atomic: write a temporary file, then rename over the target (the sync tool never sees half a file)."""
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)

    def save(self, note: Note) -> Note:
        """Writes the note; the file is created (and its name fixed) on the first save."""
        if not note.path:
            taken = {n.id for n in self.scan()}
            note_id = note.id
            while not note_id or note_id in taken:
                note_id = fmt.generate_id()
            note = note.copy(id=note_id, path=fmt.file_name_for(note.title, note_id))
        note = note.copy(has_id=True)
        self._write(note.path, fmt.serialize(note))
        mtime = (self.root / note.path).stat().st_mtime_ns
        self._cache[note.path] = (mtime, note)
        return note

    def delete(self, note: Note) -> None:
        try:
            (self.root / note.path).unlink()
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
