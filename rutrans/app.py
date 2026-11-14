"""RuEn Translator: offline Russian -> English document translator (PySide6 GUI).

Four screens, following the design sketches:
  1. Upload   - drag & drop or "Upload your document"
  2. Preview  - scrollable Russian document + Translate
  3. Progress - Russian document (locked) + progress bar with time left
  4. Result   - scrollable English document + Download
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from . import __version__
from .documents import IMAGES, SUPPORTED, output_path, translate_file
from .engine import Cancelled, Translator, ensure_glossary
from .eta import Countdown, TimeLeft
from .viewer import DocumentView, analyze, estimate_seconds

APP_NAME = "RuEn Translator"
ACCENT = "#1F5FAD"
ICON = Path(__file__).with_name("icon.ico")
SOURCE_URL = "https://github.com/Gautam1988/ruen-translator"
DOCS_DIR = Path(__file__).with_name("docs")        # LICENSE, notices, privacy (bundled)

STYLE = f"""
QMainWindow, #root {{ background: #F3F5F9; }}
#header {{ background: white; border-bottom: 1px solid #E1E6ED; }}
#title {{ font-size: 14pt; font-weight: 600; color: #1B2430; }}
#subtitle, #muted {{ color: #6B7685; }}
QLabel {{ color: #1B2430; }}
QPushButton {{ padding: 7px 14px; border-radius: 8px; border: 1px solid #CBD3DE;
              background: white; color: #1B2430; }}
QPushButton:hover {{ background: #EEF3FA; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600;
                      padding: 11px 30px; font-size: 11pt; }}
QPushButton#primary:hover {{ background: #2A6FC4; }}
QPushButton#primary:disabled {{ background: #9FB6D6; }}
QPushButton#link {{ border: none; background: transparent; color: {ACCENT}; padding: 4px 6px; }}
QPushButton#link:hover {{ text-decoration: underline; }}
#dropzone {{ background: white; border: 2px dashed #A9BCD8; border-radius: 18px; }}
#dropzone[active="true"] {{ border-color: {ACCENT}; background: #EEF4FC; }}
#floatbar, #card {{ background: white; border: 1px solid #DCE2EA; border-radius: 14px; }}
#dim {{ background: rgba(27, 36, 48, 0.28); }}
QProgressBar {{ border: none; background: #E4E9F0; border-radius: 7px; min-height: 14px;
               max-height: 14px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 7px; }}
QComboBox {{ padding: 6px 10px; border: 1px solid #CBD3DE; border-radius: 8px; background: white; }}
"""


def fmt_eta(seconds: float) -> str:
    if seconds < 10:
        return "A few seconds left"
    if seconds < 60:
        return f"About {int(round(seconds / 5) * 5)} seconds left"
    if seconds < 3600:
        m, s = divmod(int(round(seconds / 10) * 10), 60)
        return f"About {m} min {s:02d} s left" if s else f"About {m} min left"
    h, m = divmod(int(seconds // 60), 60)
    return f"About {h} h {m} min left"


def shadow(widget, blur=28, alpha=60):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, 6)
    eff.setColor(QColor(20, 30, 50, alpha))
    widget.setGraphicsEffect(eff)


# ---------------------------------------------------------------- background work

class ModelLoader(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.loaded.emit(Translator())
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return
        # Warm up OCR in the background so the first scanned page is not slow.
        try:
            from . import ocr
            if ocr.available():
                ocr.warm_up()
        except Exception:  # noqa: BLE001  (OCR problems are reported when a scan is opened)
            pass


class TranslateWorker(QThread):
    # done, total, stage, chars. "ocr": pages done/total and characters read so far;
    # "translate": characters translated/total.
    progress = Signal(int, int, str, int)
    finished_ok = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, tr, src: Path, out_dir: Path, pdf_mode: str):
        super().__init__()
        self.tr, self.src, self.out_dir, self.pdf_mode = tr, src, out_dir, pdf_mode
        self.cancel = threading.Event()

    def run(self):
        try:
            dst = translate_file(self.tr, self.src, self.out_dir, self.pdf_mode,
                                 progress=lambda d, t, stage="translate", chars=0:
                                     self.progress.emit(d, t, stage, chars),
                                 cancel=self.cancel)
            self.finished_ok.emit(str(dst))
        except Cancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class TextWorker(QThread):
    done = Signal(str)

    def __init__(self, tr, text):
        super().__init__()
        self.tr, self.text = tr, text

    def run(self):
        try:
            self.done.emit(self.tr.translate(self.text))
        except Exception as e:  # noqa: BLE001
            self.done.emit(f"Error: {e}")


# ---------------------------------------------------------------- small widgets

class DropZone(QFrame):
    """Screen 1: the dashed area you drop a document on."""
    dropped = Signal(str)

    def __init__(self, on_click):
        super().__init__()
        self.setObjectName("dropzone")
        self.setAcceptDrops(True)
        self.setMinimumSize(560, 380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(48, 40, 48, 40)
        lay.setSpacing(10)
        lay.addStretch(1)
        icon = QLabel()
        if ICON.exists():
            icon.setPixmap(QPixmap(str(ICON)).scaled(76, 76, Qt.KeepAspectRatio,
                                                      Qt.SmoothTransformation))
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)
        lay.addSpacing(8)
        head = QLabel("Drag and drop your Russian document here")
        head.setAlignment(Qt.AlignCenter)
        head.setStyleSheet("font-size: 15pt; font-weight: 600;")
        lay.addWidget(head)
        orl = QLabel("or")
        orl.setObjectName("muted")
        orl.setAlignment(Qt.AlignCenter)
        lay.addWidget(orl)
        btn = QPushButton("Upload your document")
        btn.setObjectName("primary")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(on_click)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(10)
        fmt = QLabel("Word (.docx) · PDF · text (.txt) · scanned PDFs and images (.png .jpg .tif)")
        fmt.setObjectName("muted")
        fmt.setAlignment(Qt.AlignCenter)
        lay.addWidget(fmt)
        lay.addStretch(1)

    def _active(self, on):
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._active(True)

    def dragLeaveEvent(self, e):
        self._active(False)

    def dropEvent(self, e):
        self._active(False)
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.dropped.emit(urls[0])


class Overlay(QWidget):
    """Floating bar (screens 2 and 4) or dimmed progress card (screen 3) over the document."""

    def __init__(self, parent, kind: str):
        super().__init__(parent)
        self.kind = kind
        if kind == "dim":
            self.setObjectName("dim")
            self.setAttribute(Qt.WA_StyledBackground, True)
        self.hide()

    def place(self):
        p = self.parentWidget()
        if self.kind == "dim":
            self.setGeometry(p.rect())
        else:
            self.adjustSize()
            w = min(max(self.sizeHint().width(), 520), p.width() - 32)
            h = self.sizeHint().height()
            self.setGeometry((p.width() - w) // 2, p.height() - h - 24, w, h)
        self.raise_()


class GlossaryDialog(QDialog):
    """Edit the user's term list (Russian term = English term)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Glossary — your terms")
        self.resize(720, 560)
        self.path = ensure_glossary()
        lay = QVBoxLayout(self)
        intro = QLabel("One term per line: <b>русский термин = English term</b>. Word endings are "
                       "matched loosely, so “первый контур” also finds “первом контуре”. "
                       "Lines starting with # are ignored. Changes apply to the next translation.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.edit = QPlainTextEdit()
        self.edit.setFont(QFont("Consolas", 11))
        self.edit.setPlainText(self.path.read_text(encoding="utf-8-sig"))
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)

    def _save(self):
        try:
            self.path.write_text(self.edit.toPlainText().rstrip() + "\n", encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Could not save the glossary:\n\n{e}")
            return
        self.accept()


class AboutDialog(QDialog):
    """Version, licence, source code, credits; shows the bundled licence documents."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        head = QHBoxLayout()
        if ICON.exists():
            ic = QLabel()
            ic.setPixmap(QPixmap(str(ICON)).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            head.addWidget(ic)
        title = QLabel(f"<span style='font-size:15pt; font-weight:600'>{APP_NAME}</span><br>"
                       f"<span style='color:#6B7685'>Version {__version__} · Russian → English, "
                       "works fully offline</span>")
        head.addWidget(title, 1)
        lay.addLayout(head)
        body = QLabel(
            "Translates Word, PDF and text documents, and scanned pages, from Russian to English "
            "on this PC. Nothing is uploaded, and no account is needed.<br><br>"
            "Free software under the <b>GNU Affero General Public License v3</b> or later. "
            f"Source code: <a href='{SOURCE_URL}'>{SOURCE_URL}</a><br><br>"
            "Translation model: OPUS-MT ru-en by the University of Helsinki (Language Technology "
            "Research Group), licensed CC BY 4.0. Text recognition: PaddleOCR PP-OCRv5 models via "
            "RapidOCR (Apache 2.0). PDF engine: PyMuPDF / MuPDF by Artifex (AGPL v3). "
            "Full list under Third-party notices.")
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        body.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lay.addWidget(body)
        row = QHBoxLayout()
        for label, name in (("Licence", "LICENSE"), ("Third-party notices", "THIRD_PARTY_NOTICES.md"),
                            ("Privacy", "PRIVACY.md")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, n=name, t=label: self._show_doc(n, t))
            row.addWidget(b)
        row.addStretch(1)
        ok = QPushButton("Close")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)

    def _show_doc(self, name, title):
        path = DOCS_DIR / name
        if not path.exists():                       # running from source: project root
            path = Path(__file__).resolve().parent.parent / name
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(760, 600)
        v = QVBoxLayout(dlg)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 10))
        try:
            text.setPlainText(path.read_text(encoding="utf-8"))
        except OSError:
            text.setPlainText(f"{name} was not found. See {SOURCE_URL}")
        v.addWidget(text)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        v.addWidget(close, 0, Qt.AlignRight)
        dlg.exec()


class TextDialog(QDialog):
    """Quick text translation (paste Russian, get English)."""

    def __init__(self, parent, tr):
        super().__init__(parent)
        self.tr_engine = tr
        self.worker = None
        self.setWindowTitle("Quick text translation")
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        self.src = QPlainTextEdit()
        self.src.setPlaceholderText("Paste or type Russian text…")
        self.dst = QPlainTextEdit()
        self.dst.setReadOnly(True)
        self.dst.setPlaceholderText("English translation")
        for e in (self.src, self.dst):
            e.setFont(QFont("Segoe UI", 11))
            split.addWidget(e)
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        hint = QLabel("Ctrl+Enter to translate")
        hint.setObjectName("muted")
        row.addWidget(hint)
        row.addStretch(1)
        copy = QPushButton("Copy English")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.dst.toPlainText()))
        self.go = QPushButton("Translate")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.translate)
        row.addWidget(copy)
        row.addWidget(self.go)
        lay.addLayout(row)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.translate)

    def translate(self):
        text = self.src.toPlainText()
        if not text.strip() or (self.worker and self.worker.isRunning()):
            return
        self.go.setEnabled(False)
        self.dst.setPlainText("Translating…")
        self.worker = TextWorker(self.tr_engine, text)
        self.worker.done.connect(self._done)
        self.worker.start()

    def _done(self, out):
        self.dst.setPlainText(out)
        self.go.setEnabled(True)


# ---------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    SCREENS = ("Upload", "Preview", "Translate", "Download")

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1100, 780)
        self.setMinimumSize(760, 560)
        self.tr_engine: Translator | None = None
        self.worker: TranslateWorker | None = None
        self.src: Path | None = None
        self.result: Path | None = None
        self.info: dict = {}
        self.work_root = Path(tempfile.gettempdir()) / "RuEnTranslator"
        shutil.rmtree(self.work_root, ignore_errors=True)   # leftovers of earlier runs

        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.stack.addWidget(self._build_upload())     # 0
        self.stack.addWidget(self._build_document())   # 1 (screens 2, 3 and 4 share it)
        self.go_upload()

        self.statusBar().showMessage("Loading the translator…")
        self.loader = ModelLoader()
        self.loader.loaded.connect(self._model_ready)
        self.loader.failed.connect(self._model_failed)
        self.loader.start()

        self.eta_timer = QTimer(self, interval=1000, timeout=self._tick_eta)

    # ---- header with step indicator
    def _build_header(self):
        h = QWidget()
        h.setObjectName("header")
        h.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(20, 12, 20, 12)
        if ICON.exists():
            ic = QLabel()
            ic.setPixmap(QPixmap(str(ICON)).scaled(34, 34, Qt.KeepAspectRatio,
                                                    Qt.SmoothTransformation))
            lay.addWidget(ic)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel("Russian → English Translator")
        t.setObjectName("title")
        s = QLabel("Works offline — your documents never leave this PC")
        s.setObjectName("subtitle")
        titles.addWidget(t)
        titles.addWidget(s)
        lay.addLayout(titles)
        lay.addStretch(1)
        self.steps = QLabel()
        lay.addWidget(self.steps)
        lay.addStretch(1)
        quick = QPushButton("Quick text…")
        quick.setToolTip("Translate a few sentences you paste in")
        quick.clicked.connect(self._quick_text)
        gl = QPushButton("Glossary…")
        gl.setToolTip("Your term list: Russian term = English term.\n"
                      "Used for every translation; changes apply to the next run.")
        gl.clicked.connect(self._open_glossary)
        about = QPushButton("About")
        about.setToolTip("Version, licence, source code and credits")
        about.clicked.connect(lambda: AboutDialog(self).exec())
        lay.addWidget(quick)
        lay.addWidget(gl)
        lay.addWidget(about)
        return h

    def _set_step(self, n):
        parts = []
        for i, name in enumerate(self.SCREENS, 1):
            if i < n:
                parts.append(f'<span style="color:{ACCENT}">✓ {name}</span>')
            elif i == n:
                parts.append(f'<span style="color:{ACCENT}; font-weight:600">{i} {name}</span>')
            else:
                parts.append(f'<span style="color:#9AA4B2">{i} {name}</span>')
        self.steps.setText('<span style="color:#C3CAD4">  —  </span>'.join(parts))

    # ---- screen 1
    def _build_upload(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(40, 32, 40, 32)
        lay.addStretch(1)
        self.drop = DropZone(self._pick_file)
        self.drop.dropped.connect(self.open_document)
        shadow(self.drop, 30, 35)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.drop, 3)
        row.addStretch(1)
        lay.addLayout(row, 4)
        lay.addStretch(1)
        return w

    # ---- screens 2-4: document + overlays
    def _build_document(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = DocumentView()
        lay.addWidget(self.view)

        # Screen 2: floating bar with Translate
        self.bar_preview = Overlay(self.view, "bar")
        self.bar_preview.setObjectName("floatbar")
        self.bar_preview.setAttribute(Qt.WA_StyledBackground, True)
        b = QHBoxLayout(self.bar_preview)
        b.setContentsMargins(18, 12, 12, 12)
        b.setSpacing(12)
        self.lbl_file = QLabel()
        self.lbl_file.setStyleSheet("font-weight: 600;")
        self.lbl_meta = QLabel()
        self.lbl_meta.setObjectName("muted")
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(self.lbl_file)
        names.addWidget(self.lbl_meta)
        b.addLayout(names, 1)
        self.pdf_mode = QComboBox()
        self.pdf_mode.addItem("English PDF — same page layout", "pdf")
        self.pdf_mode.addItem("English Word document — editable text", "docx")
        b.addWidget(self.pdf_mode)
        other = QPushButton("Choose another")
        other.setObjectName("link")
        other.clicked.connect(self.go_upload)
        b.addWidget(other)
        self.btn_translate = QPushButton("Translate")
        self.btn_translate.setObjectName("primary")
        self.btn_translate.setCursor(Qt.PointingHandCursor)
        self.btn_translate.clicked.connect(self.start_translation)
        b.addWidget(self.btn_translate)
        shadow(self.bar_preview)

        # Screen 3: dimmed document + centred progress card
        self.dim = Overlay(self.view, "dim")
        dl = QVBoxLayout(self.dim)
        dl.addStretch(1)
        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(520)
        shadow(card, 40, 80)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 24, 28, 22)
        cl.setSpacing(10)
        self.lbl_progress_title = QLabel("Translating…")
        self.lbl_progress_title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        cl.addWidget(self.lbl_progress_title)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        cl.addWidget(self.bar)
        row = QHBoxLayout()
        self.lbl_stage = QLabel()
        self.lbl_stage.setObjectName("muted")
        self.lbl_eta = QLabel()
        self.lbl_eta.setStyleSheet("font-weight: 600;")
        row.addWidget(self.lbl_stage, 1)
        row.addWidget(self.lbl_eta)
        cl.addLayout(row)
        crow = QHBoxLayout()
        crow.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_translation)
        crow.addWidget(self.btn_cancel)
        cl.addLayout(crow)
        hrow = QHBoxLayout()
        hrow.addStretch(1)
        hrow.addWidget(card)
        hrow.addStretch(1)
        dl.addLayout(hrow)
        dl.addStretch(1)

        # Screen 4: floating bar with Download
        self.bar_result = Overlay(self.view, "bar")
        self.bar_result.setObjectName("floatbar")
        self.bar_result.setAttribute(Qt.WA_StyledBackground, True)
        r = QHBoxLayout(self.bar_result)
        r.setContentsMargins(18, 12, 12, 12)
        r.setSpacing(12)
        self.lbl_done = QLabel()
        self.lbl_done.setStyleSheet("font-weight: 600;")
        self.lbl_saved = QLabel()
        self.lbl_saved.setObjectName("muted")
        self.lbl_saved.setOpenExternalLinks(False)
        self.lbl_saved.linkActivated.connect(self._reveal_saved)
        names2 = QVBoxLayout()
        names2.setSpacing(0)
        names2.addWidget(self.lbl_done)
        names2.addWidget(self.lbl_saved)
        r.addLayout(names2, 1)
        again = QPushButton("Translate another")
        again.setObjectName("link")
        again.clicked.connect(self.go_upload)
        r.addWidget(again)
        self.btn_download = QPushButton("Download")
        self.btn_download.setObjectName("primary")
        self.btn_download.setCursor(Qt.PointingHandCursor)
        self.btn_download.clicked.connect(self.download)
        r.addWidget(self.btn_download)
        shadow(self.bar_result)

        self.view.installEventFilter(self)
        return w

    def eventFilter(self, obj, ev):
        if obj is self.view and ev.type() == QEvent.Resize:
            for o in (self.bar_preview, self.dim, self.bar_result):
                if o.isVisible():
                    o.place()
        return super().eventFilter(obj, ev)

    def _show_overlay(self, which):
        for o in (self.bar_preview, self.dim, self.bar_result):
            o.setVisible(o is which)
        if which is not None:
            which.place()

    # ---- navigation
    def go_upload(self):
        if self.worker and self.worker.isRunning():
            return
        self.view.clear()
        self._show_overlay(None)
        self.stack.setCurrentIndex(0)
        self._set_step(1)
        self.setAcceptDrops(True)

    def _pick_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Upload your document", "",
            "Documents and scans (*.docx *.pdf *.txt *.md *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if f:
            self.open_document(f)

    def dragEnterEvent(self, e):  # dropping anywhere on screens 1-2 also works
        if self.stack.currentIndex() == 0 or self.bar_preview.isVisible():
            if e.mimeData().hasUrls():
                e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.open_document(urls[0])

    def open_document(self, path):
        """Screen 2: show the Russian document with the Translate button."""
        p = Path(path)
        if p.suffix.lower() not in SUPPORTED:
            QMessageBox.warning(self, APP_NAME,
                                f"“{p.name}” is not a supported file.\n\nUse Word (.docx), PDF, "
                                "text (.txt) or a scanned image (.png, .jpg, .tif).\n"
                                "Old .doc files: open them in Word and save as .docx first.")
            return
        try:
            self.info = analyze(p)
            self.view.load(p)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Could not open “{p.name}”:\n\n{e}")
            return
        self.src = p
        self.result = None
        self.saved = None
        pages = self.info["pages"]
        meta = f"{pages} page{'s' if pages != 1 else ''}"
        if self.info["kind"] != "pages":
            meta = "about " + meta
        if self.info["scan_pages"]:
            meta += " · scanned (text will be read with OCR)"
        meta += f" · {fmt_eta(estimate_seconds(self.info)).replace(' left', '').lower()}"
        self.lbl_file.setText(p.name)
        self.lbl_meta.setText(meta)
        is_pdf = p.suffix.lower() == ".pdf" or p.suffix.lower() in IMAGES
        self.pdf_mode.setVisible(is_pdf)
        self.view.set_locked(False)
        self.stack.setCurrentIndex(1)
        self._show_overlay(self.bar_preview)
        self._set_step(2)
        self._update_translate_button()

    def _update_translate_button(self):
        ready = self.tr_engine is not None
        self.btn_translate.setEnabled(ready)
        self.btn_translate.setText("Translate" if ready else "Loading translator…")

    # ---- screen 3
    def start_translation(self):
        if not self.tr_engine or not self.src:
            return
        out_dir = self.work_root / uuid.uuid4().hex
        out_dir.mkdir(parents=True, exist_ok=True)
        self.worker = TranslateWorker(self.tr_engine, self.src, out_dir, self.pdf_mode.currentData())
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.view.set_locked(True)
        self._show_overlay(self.dim)
        self._set_step(3)
        self.bar.setValue(0)
        self.lbl_progress_title.setText(f"Translating {self.src.name}")
        self.lbl_stage.setText("Starting…")
        self.btn_cancel.setEnabled(True)
        self.t_start = time.monotonic()
        self.timeleft = TimeLeft(self.info["scan_pages"], self.info.get("chars", 0), self.t_start)
        self.countdown = Countdown(self.timeleft.total_estimate(), self.t_start)
        self.frac = 0.0
        self.shown_eta = None
        self.two_steps = self.info["scan_pages"] > 0
        self._tick_eta()
        self.eta_timer.start()
        self.worker.start()

    def _on_progress(self, done, total, stage, chars):
        self.timeleft.update(stage, done, total, time.monotonic(),
                             chars=chars if stage == "ocr" else None)
        if stage == "ocr":
            self.lbl_stage.setText(f"Step 1 of 2 · Reading scanned pages ({done} of {total} done)")
        else:
            pct = int(100 * done / total) if total else 100
            prefix = "Step 2 of 2 · " if self.two_steps else ""
            self.lbl_stage.setText(f"{prefix}Translating the text ({pct}%)")
        self._tick_eta()

    def _tick_eta(self):
        """Every second: count down, ease in the newest estimate, move the bar to match."""
        now = time.monotonic()
        left = self.countdown.tick(self.timeleft.remaining(now), now)
        elapsed = now - self.t_start
        # The bar shows elapsed / (elapsed + time left), so bar and countdown always agree.
        self.frac = max(self.frac, min(elapsed / (elapsed + left) if elapsed + left else 0, 0.99))
        self.bar.setValue(int(self.frac * 1000))
        # Only let the displayed number go up if the rise is real (avoids flicker).
        if self.shown_eta is None or left < self.shown_eta or left > self.shown_eta * 1.15 + 3:
            self.shown_eta = left
        else:
            self.shown_eta = max(self.shown_eta - 1.0, left)
        self.lbl_eta.setText(fmt_eta(self.shown_eta) if left > 0.5 else "Finishing…")

    def cancel_translation(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.btn_cancel.setEnabled(False)
            self.lbl_stage.setText("Cancelling…")

    def _stop_progress(self):
        self.eta_timer.stop()
        self.view.set_locked(False)

    def _on_cancelled(self):
        self._stop_progress()
        self._show_overlay(self.bar_preview)
        self._set_step(2)

    def _on_failed(self, msg):
        self._stop_progress()
        self._show_overlay(self.bar_preview)
        self._set_step(2)
        QMessageBox.critical(self, APP_NAME, f"The translation did not finish:\n\n{msg}")

    # ---- screen 4
    def _on_done(self, dst):
        self._stop_progress()
        self.bar.setValue(1000)
        self.timeleft.finish(time.monotonic())     # remember this PC's speed for next time
        self.result = Path(dst)
        secs = time.monotonic() - self.t_start
        self.view.load(self.result)
        self.lbl_done.setText(f"Translated in {secs:.0f} s — {self.result.suffix[1:].upper()} ready")
        self.lbl_saved.setText("Click Download to save the English document.")
        self._show_overlay(self.bar_result)
        self._set_step(4)

    def download(self):
        if not self.result or not self.src:
            return
        suggested = output_path(self.src, None, self.result.suffix)
        f, _ = QFileDialog.getSaveFileName(self, "Download the English document", str(suggested),
                                           f"{self.result.suffix[1:].upper()} (*{self.result.suffix})")
        if not f:
            return
        try:
            shutil.copyfile(self.result, f)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Could not save the file:\n\n{e}")
            return
        self.saved = f
        self.lbl_saved.setText(f'Saved to {Path(f).name} — <a href="#">show in folder</a>')
        self.bar_result.place()          # the longer text needs a wider bar

    def _reveal_saved(self, _link):
        f = getattr(self, "saved", None)
        if not f:
            return
        if os.name == "nt":
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(f)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(f).parent)))

    # ---- header actions / model
    def _quick_text(self):
        if not self.tr_engine:
            QMessageBox.information(self, APP_NAME, "The translator is still loading — one moment.")
            return
        TextDialog(self, self.tr_engine).exec()

    def _open_glossary(self):
        # Edited inside the app: in the Store (MSIX) version the settings folder is private
        # to the app, so an outside editor such as Notepad cannot see the file.
        GlossaryDialog(self).exec()

    def _model_ready(self, tr):
        self.tr_engine = tr
        self.statusBar().showMessage("Ready — works fully offline")
        self._update_translate_button()

    def _model_failed(self, msg):
        self.statusBar().showMessage("The translator failed to load")
        QMessageBox.critical(self, APP_NAME, f"Could not load the translation model:\n\n{msg}")

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.worker.wait(5000)
        self.view.clear()
        shutil.rmtree(self.work_root, ignore_errors=True)
        super().closeEvent(e)


# ---------------------------------------------------------------- entry points

def cli(args: list[str]) -> int:
    """RuEnTranslator.exe --translate FILE... [--out DIR] [--pdf-docx]  (no window)."""
    out_dir = None
    if "--out" in args:
        i = args.index("--out")
        out_dir = Path(args[i + 1])
        del args[i:i + 2]
    mode = "docx" if "--pdf-docx" in args else "pdf"
    files = [a for a in args if not a.startswith("--")]
    log = []
    ok = 0
    try:
        tr = Translator()
        for f in files:
            try:
                log.append(f"OK   {f} -> {translate_file(tr, Path(f), out_dir, mode)}")
                ok += 1
            except Exception as e:  # noqa: BLE001
                log.append(f"FAIL {f}: {e}")
    except Exception:  # noqa: BLE001
        import traceback
        log.append("ERROR\n" + traceback.format_exc())
    text = "\n".join(log)
    try:
        print(text)
    except Exception:  # noqa: BLE001  (no console in the windowed build)
        pass
    if out_dir:
        (out_dir / "RuEnTranslator.log").write_text(text + "\n", encoding="utf-8")
    return 0 if ok == len(files) else 1


def main():
    if "--translate" in sys.argv:
        args = sys.argv[1:]
        args.remove("--translate")
        sys.exit(cli(args))
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Aexonlab.RuEnTranslator")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setPalette(app.style().standardPalette())   # light look even in Windows dark mode
    app.setFont(QFont("Segoe UI", 9))
    app.setStyleSheet(STYLE)
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))
    win = MainWindow()
    files = [a for a in sys.argv[1:] if not a.startswith("--")]
    if files:
        win.open_document(files[0])
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
