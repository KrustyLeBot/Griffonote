from griffonote_win.core import note as fmt

SAMPLE = """---
id: x81bq0
title: Idées appli
color: yellow
pinned: true
labels: [perso, dev]
reminder: 2026-10-25T09:00:00+02:00
created: 2026-10-23T14:30:00+02:00
updated: 2026-10-23T15:02:11+02:00
obsidian-tags:
  - a
  - b
---

Texte libre avec un lien https://exemple.com

- [ ] Item à faire
- [x] Item fait

![](attachments/x81bq0-01.jpg)
"""


def test_parses_known_fields():
    n = fmt.parse("idees-appli-x81bq0.md", SAMPLE, 0)
    assert (n.id, n.title, n.color, n.pinned) == ("x81bq0", "Idées appli", "yellow", True)
    assert n.labels == ["perso", "dev"]
    assert n.reminder == fmt.parse_time("2026-10-25T09:00:00+02:00")
    assert not n.conflict


def test_round_trip_keeps_unknown_fields_and_body():
    n = fmt.parse("a.md", SAMPLE, 0)
    text = fmt.serialize(n)
    assert "obsidian-tags:\n  - a\n  - b\n" in text
    again = fmt.parse("a.md", text, 0)
    assert again == n
    assert again.extra == ["obsidian-tags:", "  - a", "  - b"]


def test_titles_needing_quotes_round_trip():
    base = fmt.parse("a.md", SAMPLE, 0)
    for title in ["a: b", "# not a comment", "true", "42", "- dash", 'say "hi"', "back\\slash", ""]:
        n = base.copy(title=title, labels=["x, y", "z"])
        back = fmt.parse("a.md", fmt.serialize(n), 0)
        assert back.title == title
        assert back.labels == ["x, y", "z"]


def test_file_without_frontmatter_is_accepted():
    n = fmt.parse("liste-courses.md", "Lait\nPain\n", 1000)
    assert not n.has_id
    assert n.title == "liste courses"
    assert n.body == "Lait\nPain"
    assert len(n.id) == 6


def test_conflict_files_are_flagged():
    assert fmt.parse("courses-k3f9a2.conflict-2.md", SAMPLE, 0).conflict


def test_slug_and_file_name():
    assert fmt.slug("Idées  appli !") == "idees-appli"
    assert fmt.slug("???") == "note"
    assert fmt.file_name_for("Courses", "k3f9a2") == "courses-k3f9a2.md"


def test_plain_body_renders_checklists():
    n = fmt.parse("a.md", SAMPLE, 0)
    assert "☐ Item à faire" in n.plain_body() and "☑ Item fait" in n.plain_body()


def test_scanned_pdf_survives_a_round_trip():
    note = fmt.parse("scan-k3f9a2.md", "---\nid: k3f9a2\ntitle: Scan\npdf: attachments/scan-k3f9a2.pdf\n"
                     "created: 2026-10-25T10:00:00Z\nupdated: 2026-10-25T10:00:00Z\n---\n", 0)
    assert note.pdf == "attachments/scan-k3f9a2.pdf"
    assert note.extra == []
    assert "pdf: attachments/scan-k3f9a2.pdf" in fmt.serialize(note)
    assert fmt.parse("plain.md", "---\nid: abc123\ntitle: x\n---\n", 0).pdf is None
