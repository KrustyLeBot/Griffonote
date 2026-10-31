# Griffonote

A simple Google Keep replacement for Android. Every note is a plain Markdown file in a
folder (`Documents/Griffonote/` by default), so notes can be read and edited on a PC
(Obsidian, any editor) and synced by a separate app. The user never sees Markdown on the phone.

## Storage format

```
Griffonote/
├── courses-k3f9a2.md      # one file per note: YAML frontmatter + Markdown body
├── attachments/           # scanned PDFs (`pdf:`), attached files (`attachments:`) and activity tracks
├── activities/            # the "Activités" folder: one note per activity, kept out of the regular list
└── drawings/
```

- A scan is a normal note whose frontmatter has `pdf: attachments/<name>.pdf`; the Android app creates it
  with Google's document scanner (automatic page corners, several pages) and fits each page on A4 or
  US Letter (guessed from the page shape, or fixed in the settings), compressed for a fast sync.
- Files attached to a note (photos, videos, any document) are copied to `attachments/<name>-<id6>.<ext>` and
  listed in its frontmatter: `attachments: [attachments/facture-edf-k3f9a2.pdf, ...]`. On Android they come from
  the gallery or the file manager (paperclip button of the editor), on Windows from a file dialog; 50 MB at most
  each. Deleting the note or removing an attachment deletes its file.
- The file name is fixed at creation (`<slug>-<id6>.md`) and never renamed.
- Unknown frontmatter fields are preserved verbatim.
- Writes are atomic: `.<name>.synctmp-<uuid>` in the same folder, flushed to disk, then renamed over the file (Synchrotron never syncs that pattern).
- The folder is the source of truth; the in-memory index is rebuilt on launch, on resume
  and when files change on disk.

## Activities

The pinned "Activités" entry of the notes list opens a separate folder (`activities/`): figures for the
week, the month and overall, then the latest activities (walking, cycling, skiing, other with or without GPS).

- An activity is a note whose frontmatter has `activity: {"sport": "ski", "start": <ms>, "elapsed": <s>, "moving": <s>,
  "distance": <m>, "ascent": <m>, "descent": <m>, "hr": <bpm>, "vmax": <m/s>, "runs": <n>, "file": "attachments/….fit"}`:
  what the list shows without opening the track. The track itself is one **FIT** (or **GPX**, for imports) file in
  `attachments/`, listed in `attachments:` with the photos. Everything shown (map, figures, charts) is recomputed
  from that file, so the analysis can improve without touching old activities.
- Import: any FIT (Coros and other watches, Strava's "original file" export) or GPX file, one at a time, from the
  "Importer FIT / GPX" button. Recording (Android only): GPS in a foreground service, a log written as it goes
  (a crash loses nothing), turned into a FIT file when the activity ends. A time-only sport has no file; its
  distance can be typed afterwards (treadmill).
- Analysis (same algorithms in Kotlin and Python, tested on synthetic tracks): GPS jumps dropped; **stops** found
  by position (nothing moved more than 8 m for 30 s, about 1 km/h), on top of the pauses made with the button, and
  both left out of the moving time, the distance and the average pace; climb with a 3 m hysteresis on a smoothed
  altitude; skiing is cut into **descents** (altitude falling and fast enough), the only part counted for the
  skiing figures and drawn on the map. Without altitude in a file, descents fall back on speed.
- Altitude when recording: the barometer gives the changes, the GPS keeps it honest (the gap between both is
  followed with a 5 minute time constant). The consolidated altitude is the standard FIT field; the raw GPS
  altitude and the pressure are kept as developer fields (`gps_altitude`, `pressure`).
- GPS rate while recording: 5 s walking, 2 s cycling and skiing, 3 s other; "Économie de batterie" uses 12 s.
- The map is OpenStreetMap raster tiles drawn by hand (no map library, no web engine), cached on disk (100 MB at
  most, oldest purged) and fetched only online; offline only the track is drawn. Tiles are requested with an
  identifying User-Agent, as the tile usage policy asks.
- FIT is read and written with a small implementation of the public format (`Fit.kt`, `fit.py`), no SDK.
- Tests use synthetic tracks only: this repository is public and a real track reveals where you live.

## Status

Milestones 1–2 and 6 (partly) are implemented: text notes, checklists (drag to reorder,
checked items folded), colours, pin, labels, full-text search,
grid/list view, share in/out (text), conflict-file badge, external-change handling,
settings, self-update. Images, drawings and reminders (milestones 3–5) are not done yet.

## Windows client

`windows/` holds a Python 3.12 + PySide6 desktop client that works on the same notes folder
(pick it at first launch; it is remembered). It reads and writes the same Markdown files,
atomically, watches the folder for changes made by the sync tool, and updates itself from
the `latest` release (checks size and SHA-256, swaps the exe, restarts).

```
cd windows
pip install -r requirements.txt pytest
python -m pytest tests -q
python run.py
```

The CI builds `Griffonote.exe` (PyInstaller, one file) and publishes it next to the APK in the
`latest` release. The exe is not signed, so SmartScreen may warn the first time.

## Build

```
./gradlew assembleRelease
```

Local builds use Android's default debug key (release builds fall back to it without the CI key). CI (`.github/workflows/build-apk.yml`) signs
builds with a private key stored in the `release` GitHub environment and publishes the
rolling `latest` release that the in-app updater reads.

### One-time signing setup

```bash
keytool -genkeypair -keystore griffonote.jks -alias griffonote \
  -keyalg RSA -keysize 4096 -validity 36500 \
  -dname "CN=Griffonote, O=Griffonote, C=FR"
base64 -w0 griffonote.jks > griffonote.jks.b64
```

Then in GitHub → Settings → Environments → `release` (deployment branches: `main` only), add
the secrets `KEYSTORE_BASE64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`.
Back up the `.jks` and passwords offline; a lost key means no more updates.
