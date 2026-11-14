# SPDX-License-Identifier: AGPL-3.0-or-later
"""Store screenshots (1366x768): drives the app off-screen through its four screens.

Usage: python packaging/make_screenshots.py DOCUMENT [OUT_DIR]
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ruen_shots_")      # don't touch real settings
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from rutrans import app as appmod  # noqa: E402

doc = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent / "store-screenshots").resolve()
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True)
saved = Path(tempfile.mkdtemp(prefix="ruen_saved_"))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(saved / Path(a[2]).name), ""))

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setPalette(app.style().standardPalette())
app.setFont(QFont("Segoe UI", 9))
app.setStyleSheet(appmod.STYLE)
win = appmod.MainWindow()
win.resize(1366, 768)
win.show()


def snap(name, widget=None):
    app.processEvents()
    (widget or win).grab().save(str(out / name))
    print("saved", name)


def step1(_):
    QTimer.singleShot(1500, lambda: (snap("1-upload.png"), step2()))


def step2():
    win.open_document(str(doc))
    QTimer.singleShot(1200, step3)


def show_page(n):
    """Scroll the document view so that page n (0-based) is at the top."""
    labels = win.view.pages.labels
    if len(labels) > n:
        win.view.pages.verticalScrollBar().setValue(labels[n].y() - 12)


def step3():
    show_page(1)
    QTimer.singleShot(800, lambda: (snap("2-preview-and-translate.png"), step4()))


def step4():
    win.start_translation()
    taken = {"done": False}

    def maybe(*_):
        if not taken["done"] and win.frac > 0.35:
            taken["done"] = True
            QTimer.singleShot(0, lambda: snap("3-progress-time-left.png"))
    win.worker.progress.connect(maybe)
    win.worker.finished_ok.connect(lambda _: QTimer.singleShot(1500, step5))


def step5():
    win.download()
    QTimer.singleShot(600, lambda: show_page(1))
    QTimer.singleShot(1400, lambda: (snap("4-english-result-download.png"), step6()))


def step6():
    dlg = appmod.GlossaryDialog(win)
    dlg.edit.setPlainText(dlg.edit.toPlainText() + "\nпервый контур = primary circuit\n"
                          "активная зона = reactor core\nтеплоноситель = coolant\n")
    dlg.resize(720, 480)
    dlg.show()
    QTimer.singleShot(500, lambda: (snap("5-glossary.png", dlg), dlg.close(), step7()))


def step7():
    dlg = appmod.AboutDialog(win)
    dlg.show()
    QTimer.singleShot(500, lambda: (snap("6-about.png", dlg), dlg.close(), app.exit(0)))


win.loader.loaded.connect(step1)
QTimer.singleShot(1800000, lambda: app.exit(1))
t0 = time.time()
code = app.exec()
print(f"done in {time.time() - t0:.0f}s -> {out}")
sys.exit(code)
