# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate the MSIX tile and logo images (scale and target-size variants) into a folder.

Usage: python packaging/make_store_assets.py <out_dir>
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

# name -> ((width, height) at scale-100, share of the tile height the icon fills)
TILES = {
    "Square44x44Logo": ((44, 44), 1.0),
    "Square150x150Logo": ((150, 150), 0.62),
    "Wide310x150Logo": ((310, 150), 0.62),
    "Square71x71Logo": ((71, 71), 0.75),
    "Square310x310Logo": ((310, 310), 0.55),
    "StoreLogo": ((50, 50), 1.0),
}
SCALES = (100, 125, 150, 200, 400)
TARGET_SIZES = (16, 24, 32, 48, 256)        # taskbar / Start / Explorer icons


def master(size=1024) -> QImage:
    """The app icon (Я → A on a blue tile), drawn at high resolution."""
    k = size / 256
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setBrush(QColor("#1F5FAD"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(8 * k, 8 * k, 240 * k, 240 * k), 48 * k, 48 * k)
    f = QFont("Segoe UI", 1, QFont.Bold)
    f.setPixelSize(int(118 * k))
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(14 * k, 20 * k, 120 * k, 150 * k), Qt.AlignCenter, "Я")
    p.drawText(QRectF(122 * k, 86 * k, 120 * k, 150 * k), Qt.AlignCenter, "A")
    f.setPixelSize(int(64 * k))
    p.setFont(f)
    p.setPen(QColor("#9CC8FF"))
    p.drawText(QRectF(80 * k, 70 * k, 96 * k, 96 * k), Qt.AlignCenter, "→")
    p.end()
    return img


def icon(m: QImage, px: int) -> QImage:
    return m.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def tile(m: QImage, w: int, h: int, fill: float) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    px = max(8, int(round(min(w, h) * fill)))
    p = QPainter(img)
    p.drawImage((w - px) // 2, (h - px) // 2, icon(m, px))
    p.end()
    return img


def main(out_dir):
    app = QGuiApplication(sys.argv)  # noqa: F841  (needed for fonts)
    os.makedirs(out_dir, exist_ok=True)
    m = master()
    count = 0
    for name, ((w, h), fill) in TILES.items():
        for scale in SCALES:
            tile(m, round(w * scale / 100), round(h * scale / 100), fill).save(
                os.path.join(out_dir, f"{name}.scale-{scale}.png"))
            count += 1
    for size in TARGET_SIZES:
        for suffix in ("", "_altform-unplated", "_altform-lightunplated"):
            icon(m, size).save(os.path.join(out_dir, f"Square44x44Logo.targetsize-{size}{suffix}.png"))
            count += 1
    print(f"wrote {count} images to {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Assets")
