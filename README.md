# Griffonote

A simple Google Keep replacement for Android. Every note is a plain Markdown file in a
folder (`Documents/Griffonote/` by default), so notes can be read and edited on a PC
(Obsidian, any editor) and synced by a separate app. The user never sees Markdown on the phone.

## Storage format

```
Griffonote/
├── courses-k3f9a2.md      # one file per note: YAML frontmatter + Markdown body
├── attachments/
└── drawings/
```

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

## Build

```
./gradlew assembleDebug
```

Local builds use Android's default debug key. CI (`.github/workflows/build-apk.yml`) signs
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
