# Griffonote

A simple Google Keep replacement for Android. Every note is a plain Markdown file in a
folder (`Documents/Griffonote/` by default), so notes can be read and edited on a PC
(Obsidian, any editor) and synced by a separate app. The user never sees Markdown on the phone.

## Storage format

```
Griffonote/
├── courses-k3f9a2.md      # one file per note: YAML frontmatter + Markdown body
├── attachments/           # scanned documents (scan-...-k3f9a2.pdf), referenced by `pdf:` in a note
└── drawings/
```

- A scan is a normal note whose frontmatter has `pdf: attachments/<name>.pdf`; the Android app creates it
  with Google's document scanner (automatic page corners, several pages) and fits each page on A4 or
  US Letter (guessed from the page shape, or fixed in the settings), compressed for a fast sync.
- The file name is fixed at creation (`<slug>-<id6>.md`) and never renamed.
- Unknown frontmatter fields are preserved verbatim.
- Writes are atomic (temporary file, then rename).
- The folder is the source of truth; the in-memory index is rebuilt on launch, on resume
  and when files change on disk.

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
