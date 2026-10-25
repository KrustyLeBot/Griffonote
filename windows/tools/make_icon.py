"""Draws the app icon (PNG + ICO) with Qt only. Run: python tools/make_icon.py"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

app = QGuiApplication(sys.argv)
size = 256
image = QImage(size, size, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
p = QPainter(image)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setBrush(QColor("#F9A825"))
p.setPen(Qt.PenStyle.NoPen)
p.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)
# the note sheet with a folded corner
sheet = QPainterPath()
sheet.moveTo(70, 56)
sheet.lineTo(150, 56)
sheet.lineTo(190, 96)
sheet.lineTo(190, 200)
sheet.lineTo(70, 200)
sheet.closeSubpath()
p.setBrush(QColor("#FFFFFF"))
p.drawPath(sheet)
p.setBrush(QColor("#E0B050"))
fold = QPainterPath()
fold.moveTo(150, 56)
fold.lineTo(190, 96)
fold.lineTo(150, 96)
fold.closeSubpath()
p.drawPath(fold)
# text lines
p.setBrush(QColor("#5D4037"))
for y, w in [(116, 90), (136, 90), (156, 56)]:
    p.drawRoundedRect(QRectF(88, y, w, 8), 4, 4)
p.end()

assets = Path(__file__).resolve().parent.parent / "griffonote_win" / "assets"
assets.mkdir(parents=True, exist_ok=True)
image.save(str(assets / "icon.png"))
image.save(str(assets / "icon.ico"))
print("written", assets)
