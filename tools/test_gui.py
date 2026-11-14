"""Drive the 4-screen GUI off-screen and save a screenshot of every screen.

Usage: python tools/test_gui.py samples [file ...]   (default: a Word file and a scanned PDF)
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from rutrans import app as appmod  # noqa: E402

samples = Path(sys.argv[1] if len(sys.argv) > 1 else "samples").resolve()
files = [samples / f for f in (sys.argv[2:] or ["report_ru.docx", "scan_ru.pdf"])]
shots = samples / "gui_shots"
import shutil  # noqa: E402

shutil.rmtree(shots, ignore_errors=True)
shots.mkdir()

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setPalette(app.style().standardPalette())
app.setFont(QFont("Segoe UI", 9))
app.setStyleSheet(appmod.STYLE)
win = appmod.MainWindow()
win.resize(1100, 780)
win.show()
log = []
queue = list(files)
saved_to = shots / "downloaded"
saved_to.mkdir(exist_ok=True)
# "Download" opens a Save dialog; answer it automatically.
QFileDialog.getSaveFileName = staticmethod(
    lambda *a, **k: (str(saved_to / Path(a[2]).name), ""))


def snap(name):
    app.processEvents()
    win.grab().save(str(shots / f"{name}.png"))


def fail(msg):
    print("FAIL:", msg)
    app.exit(1)


def next_file():
    if not queue:
        app.exit(0)
        return
    f = queue.pop(0)
    tag = f.name.replace(".", "_")
    win.go_upload()
    snap(f"{tag}_1_upload")
    win.open_document(str(f))
    QTimer.singleShot(400, lambda: screen2(tag))


def screen2(tag):
    snap(f"{tag}_2_preview")
    log.append(f"[{tag}] preview: {win.lbl_file.text()} | {win.lbl_meta.text()} | "
               f"translate enabled={win.btn_translate.isEnabled()}")
    win.start_translation()
    win.worker.progress.connect(lambda d, t, s, c: mid(tag, d, t))
    win.worker.finished_ok.connect(lambda _: QTimer.singleShot(500, lambda: screen4(tag)))
    win.worker.failed.connect(fail)


taken = set()


def mid(tag, done, total):
    import time
    for mark in (0.1, 0.5, 0.9):
        key = (tag, mark)
        if key not in taken and win.frac >= mark:
            taken.add(key)
            elapsed = time.monotonic() - win.t_start
            if mark == 0.5:
                QTimer.singleShot(0, lambda: snap(f"{tag}_3_progress"))
            log.append(f"[{tag}] at {int(win.frac * 100)}% after {elapsed:.0f}s: "
                       f"{win.lbl_stage.text()} | {win.lbl_eta.text()} | locked={win.view._lock.locked}")


def screen4(tag):
    snap(f"{tag}_4_result")
    win.download()
    app.processEvents()
    snap(f"{tag}_4_downloaded")
    log.append(f"[{tag}] result: {win.lbl_done.text()} | {win.lbl_saved.text()}")
    QTimer.singleShot(200, next_file)


def ready(_):
    QTimer.singleShot(300, next_file)


win.loader.loaded.connect(ready)
win.loader.failed.connect(fail)
QTimer.singleShot(300000, lambda: fail("timeout"))
code = app.exec()
print("\n".join(log))
print("downloaded:", sorted(f.name for f in saved_to.iterdir()))
sys.exit(code)
