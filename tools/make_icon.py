"""Draw the app icon (Я → A on a blue tile) and save it as rutrans/icon.ico."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

app = QGuiApplication(sys.argv)
size = 256
img = QImage(size, size, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.setBrush(QColor("#1F5FAD"))
p.setPen(Qt.NoPen)
p.drawRoundedRect(QRectF(8, 8, 240, 240), 48, 48)
p.setPen(QColor("white"))
f = QFont("Segoe UI", 1, QFont.Bold)
f.setPixelSize(118)
p.setFont(f)
p.drawText(QRectF(14, 20, 120, 150), Qt.AlignCenter, "Я")
p.drawText(QRectF(122, 86, 120, 150), Qt.AlignCenter, "A")
f.setPixelSize(64)
p.setFont(f)
p.setPen(QColor("#9CC8FF"))
p.drawText(QRectF(80, 70, 96, 96), Qt.AlignCenter, "→")
p.end()
out = Path(__file__).resolve().parent.parent / "rutrans" / "icon.ico"
print("saved" if img.save(str(out)) else "FAILED", out)
img.save(str(out.with_suffix(".png")))
