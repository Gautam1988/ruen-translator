"""Record the progress screen once a second while translating a document, and judge the
time-left display: how far off it was, and whether it ever jumped up.

Usage: python tools/test_eta.py FILE [FILE ...]
Uses a private speed.json (APPDATA is redirected), unless --keep-rates is given.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if "--keep-rates" not in sys.argv:
    os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ruen_eta_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rutrans import app as appmod  # noqa: E402

files = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]
app = QApplication(sys.argv)
win = appmod.MainWindow()
win.show()
trace, results = [], []


def sample():
    if win.worker and win.worker.isRunning():
        trace.append((time.monotonic() - win.t_start, win.shown_eta, win.frac,
                      win.lbl_eta.text(), win.lbl_stage.text()))


sampler = QTimer(interval=1000, timeout=sample)


def run_next():
    if not files:
        app.exit(0)
        return
    f = files.pop(0)
    trace.clear()
    win.open_document(str(f))
    first = appmod.estimate_seconds(win.info)
    win.start_translation()
    sampler.start()
    win.worker.finished_ok.connect(lambda _: QTimer.singleShot(100, lambda: report(f, first)))


def report(f, first):
    sampler.stop()
    total = time.monotonic() - win.t_start
    ups, worst = 0, 0.0
    prev = None
    print(f"\n=== {f.name}: first estimate {first:.0f}s, actual {total:.0f}s")
    for t, eta, frac, text, stage in trace:
        actual_left = total - t
        worst = max(worst, abs(eta - actual_left)) if t > 0.15 * total else worst
        if prev is not None and eta > prev + 1.5:
            ups += 1
        prev = eta
        if int(t) % max(1, int(total / 12)) == 0:
            print(f"  t={t:5.1f}s  shows {text:26s} (really {actual_left:5.1f}s left)  "
                  f"bar {frac * 100:4.0f}%  {stage}")
    print(f"  upward jumps: {ups};  worst error after the first 15%: {worst:.1f}s")
    QTimer.singleShot(500, run_next)


win.loader.loaded.connect(lambda _: QTimer.singleShot(3000, run_next))   # let OCR warm up
app.exec()
