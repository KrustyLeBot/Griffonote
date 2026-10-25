from __future__ import annotations

from PySide6.QtGui import QColor, QGuiApplication, QPalette

# id -> (light, dark), same palette as the Android app
NOTE_COLORS = {
    "red": ("#F28B82", "#77172E"),
    "orange": ("#FBBC04", "#692B17"),
    "yellow": ("#FFF475", "#7C4A03"),
    "green": ("#CCFF90", "#264D3B"),
    "teal": ("#A7FFEB", "#0C625D"),
    "blue": ("#CBF0F8", "#256377"),
    "darkblue": ("#AECBFA", "#284255"),
    "purple": ("#D7AEFB", "#472E5B"),
    "pink": ("#FDCFE8", "#6C394F"),
    "brown": ("#E6C9A8", "#4B443A"),
    "gray": ("#E8EAED", "#232427"),
}


def is_dark() -> bool:
    app = QGuiApplication.instance()
    return app is not None and app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def note_background(color_id: str) -> QColor | None:
    """Background for a note colour id, or None for the default (use the window palette)."""
    pair = NOTE_COLORS.get(color_id)
    return QColor(pair[1] if is_dark() else pair[0]) if pair else None


def note_foreground(color_id: str) -> QColor | None:
    if color_id not in NOTE_COLORS:
        return None
    return QColor("#E8EAED") if is_dark() else QColor("#202124")


def stylesheet() -> str:
    dark = is_dark()
    surface = "#2B2B2B" if dark else "#FFFFFF"
    outline = "#4A4A4A" if dark else "#D0D0D0"
    accent = "#FFB950" if dark else "#8A5A00"
    return f"""
    QFrame#toast {{ background: {surface}; border: 1px solid {outline}; border-radius: 12px; }}
    QFrame#banner {{ background: {'#4A3B1F' if dark else '#FFF1CC'}; border-radius: 8px; }}
    QPushButton#primary {{ background: {accent}; color: {'#1E1B16' if dark else '#FFFFFF'}; border: none;
                           border-radius: 6px; padding: 6px 14px; }}
    QPushButton#primary:disabled {{ background: {outline}; }}
    QProgressBar {{ background: {outline}; border: none; border-radius: 2px; }}
    QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}
    QLineEdit#search {{ border: 1px solid {outline}; border-radius: 16px; padding: 6px 12px; }}
    QLineEdit#title {{ border: none; font-size: 18pt; font-weight: 600; background: transparent; }}
    QLineEdit#labels {{ border: none; background: transparent; }}
    QPlainTextEdit {{ border: none; background: transparent; font-size: 11pt; }}
    """
