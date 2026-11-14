"""In-app document preview: PDF/scanned pages, Word documents and text files."""
from __future__ import annotations

import html
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .documents import IMAGES, _decode, _needs_ocr

CANVAS = "#E8ECF2"
BOTTOM_PAD = 120          # room for the floating action bar under the last page
MAX_PAGE_WIDTH = 860


# ---------------------------------------------------------------- document info

def open_pages(path: Path):
    """PDFs and images as a PyMuPDF document (images are converted to PDF pages)."""
    import pymupdf
    if path.suffix.lower() in IMAGES:
        img = pymupdf.open(str(path))
        doc = pymupdf.open("pdf", img.convert_to_pdf())
        img.close()
        return doc
    return pymupdf.open(str(path))


def _russian_chars(text: str) -> int:
    """Characters that will actually be translated (lines with Russian in them)."""
    from .engine import CYRILLIC
    return sum(len(ln) for ln in text.splitlines() if CYRILLIC.search(ln))


def analyze(path: Path) -> dict:
    """Pages, scanned pages and Russian characters (typed text), for the time estimate."""
    ext = path.suffix.lower()
    if ext == ".pdf" or ext in IMAGES:
        doc = open_pages(path)
        scans, chars = 0, 0
        for p in doc:
            if ext in IMAGES or _needs_ocr(p):
                scans += 1
            else:
                chars += _russian_chars(p.get_text())
        info = {"kind": "pages", "pages": doc.page_count, "scan_pages": scans, "chars": chars}
        doc.close()
        return info
    if ext == ".docx":
        import docx
        d = docx.Document(str(path))
        text = "\n".join(p.text for p in d.paragraphs)
        text += "\n" + "\n".join(c.text for t in d.tables for r in t.rows for c in r.cells)
        chars = _russian_chars(text)
        return {"kind": "html", "pages": max(1, round(chars / 2000)), "scan_pages": 0,
                "chars": chars}
    text = _decode(path.read_bytes())
    chars = _russian_chars(text)
    return {"kind": "text", "pages": max(1, round(len(text) / 2000)), "scan_pages": 0,
            "chars": chars}


def estimate_seconds(info: dict) -> float:
    """First guess before starting, from this PC's remembered speed (see eta.py)."""
    import time

    from .eta import TimeLeft
    return TimeLeft(info["scan_pages"], info.get("chars", 0), time.monotonic()).total_estimate()


# ---------------------------------------------------------------- Word -> HTML

def docx_to_html(path: Path) -> str:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    out, in_list = [], False

    def runs_html(p):
        parts = []
        for r in p.runs:
            t = html.escape(r.text)
            if not t:
                continue
            if r.bold:
                t = f"<b>{t}</b>"
            if r.italic:
                t = f"<i>{t}</i>"
            if r.underline:
                t = f"<u>{t}</u>"
            parts.append(t)
        return "".join(parts) or html.escape(p.text)

    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            style = (p.style.name if p.style is not None else "") or ""
            text = runs_html(p)
            is_list = "List" in style or child.find(".//{*}numPr") is not None
            if is_list and not in_list:
                out.append("<ul>")
                in_list = True
            elif not is_list and in_list:
                out.append("</ul>")
                in_list = False
            m = re.match(r"Heading (\d)", style)
            if style == "Title":
                out.append(f"<h1>{text}</h1>")
            elif m:
                lvl = min(int(m.group(1)), 4)
                out.append(f"<h{lvl}>{text}</h{lvl}>")
            elif is_list:
                out.append(f"<li>{text}</li>")
            elif text.strip():
                out.append(f"<p>{text}</p>")
            else:
                out.append("<p>&nbsp;</p>")
        elif tag == "tbl":
            if in_list:
                out.append("</ul>")
                in_list = False
            t = Table(child, d)
            rows = []
            for r in t.rows:
                cells = "".join(f"<td>{html.escape(c.text)}</td>" for c in r.cells)
                rows.append(f"<tr>{cells}</tr>")
            out.append('<table border="1" cellspacing="0" cellpadding="6" width="100%">'
                       + "".join(rows) + "</table><p></p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# ---------------------------------------------------------------- widgets

class _ScrollLock(QObject):
    """Swallows wheel/keyboard/scroll-bar input while the viewer is locked."""

    def __init__(self):
        super().__init__()
        self.locked = False

    def eventFilter(self, obj, ev):
        if self.locked and ev.type() in (QEvent.Wheel, QEvent.KeyPress, QEvent.MouseButtonPress,
                                         QEvent.MouseMove, QEvent.Gesture):
            return True
        return False


class PageView(QScrollArea):
    """PDF / scanned pages, rendered lazily as they scroll into view."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(f"QScrollArea {{ background: {CANVAS}; }}")
        self.inner = QWidget()
        self.inner.setStyleSheet(f"background: {CANVAS};")
        self.vbox = QVBoxLayout(self.inner)
        self.vbox.setContentsMargins(24, 24, 24, BOTTOM_PAD)
        self.vbox.setSpacing(18)
        self.vbox.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setWidget(self.inner)
        self.doc = None
        self.labels: list[QLabel] = []
        self.rendered: set[int] = set()
        self._width = 0
        self._timer = QTimer(self, singleShot=True, interval=40, timeout=self._render_visible)
        self.verticalScrollBar().valueChanged.connect(lambda _: self._timer.start())

    def set_document(self, doc):
        if self.doc is not None:
            self.doc.close()
        self.doc = doc
        for lb in self.labels:
            lb.deleteLater()
        self.labels, self.rendered = [], set()
        for i in range(doc.page_count):
            lb = QLabel()
            lb.setAlignment(Qt.AlignCenter)
            lb.setStyleSheet("background: white; border: 1px solid #D3DAE4;")
            self.vbox.addWidget(lb, 0, Qt.AlignHCenter)
            self.labels.append(lb)
        self._width = 0
        self.verticalScrollBar().setValue(0)
        self._layout_pages()

    def clear(self):
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        for lb in self.labels:
            lb.deleteLater()
        self.labels, self.rendered = [], set()

    def _page_width(self):
        return max(200, min(MAX_PAGE_WIDTH, self.viewport().width() - 48))

    def _layout_pages(self):
        if self.doc is None:
            return
        w = self._page_width()
        if w == self._width:
            return
        self._width = w
        for i, lb in enumerate(self.labels):
            r = self.doc[i].rect
            lb.setFixedSize(w, int(w * r.height / r.width))
            lb.clear()
        self.rendered = set()
        self._timer.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_pages()

    def showEvent(self, e):
        super().showEvent(e)
        self._layout_pages()
        self._timer.start()

    def _render_visible(self):
        if self.doc is None or not self.labels:
            return
        import pymupdf
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        visible = [i for i, lb in enumerate(self.labels)
                   if lb.y() + lb.height() >= top - 400 and lb.y() <= bottom + 400]
        dpr = self.devicePixelRatioF()
        for i in visible:
            if i in self.rendered:
                continue
            lb = self.labels[i]
            page = self.doc[i]
            zoom = lb.width() * dpr / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_RGB888).copy()
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            lb.setPixmap(pm)
            self.rendered.add(i)
        # Free pages far away from the view (keeps memory flat on long documents).
        if visible:
            for i in list(self.rendered):
                if i < visible[0] - 6 or i > visible[-1] + 6:
                    self.labels[i].clear()
                    self.rendered.discard(i)


class SheetView(QTextBrowser):
    """Word or text content on a white 'sheet of paper' centred on a grey canvas."""

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.setFont(QFont("Segoe UI", 11))
        self.setStyleSheet(f"QTextBrowser {{ background: {CANVAS}; border: none; }}")
        self.viewport().setStyleSheet("background: white; color: #1B2430;")
        self.document().setDocumentMargin(48)

    def resizeEvent(self, e):
        side = max(24, (self.width() - MAX_PAGE_WIDTH) // 2)
        self.setViewportMargins(side, 24, side, 0)
        super().resizeEvent(e)

    def set_html(self, body: str):
        css = ("<style>h1{font-size:20pt} h2{font-size:15pt} h3,h4{font-size:12pt}"
               "p{margin-bottom:10px; line-height:140%} td{padding:6px}</style>")
        # Trailing space so the floating action bar never covers the last lines.
        self.setHtml(css + body + f'<div style="height:{BOTTOM_PAD}px">&nbsp;</div>')
        self.verticalScrollBar().setValue(0)

    def set_text(self, text: str):
        body = "".join(f"<p>{html.escape(par).replace(chr(10), '<br>')}</p>"
                       for par in re.split(r"\n\s*\n", text)) or "<p></p>"
        self.set_html(body)


class DocumentView(QStackedWidget):
    """Shows any supported file; scrolling can be locked (progress screen)."""

    def __init__(self):
        super().__init__()
        self.pages = PageView()
        self.sheet = SheetView()
        self.addWidget(self.pages)
        self.addWidget(self.sheet)
        self._lock = _ScrollLock()
        for w in (self.pages, self.sheet):
            w.viewport().installEventFilter(self._lock)
            w.installEventFilter(self._lock)
            w.verticalScrollBar().installEventFilter(self._lock)

    def load(self, path: Path):
        ext = path.suffix.lower()
        if ext == ".pdf" or ext in IMAGES:
            self.pages.set_document(open_pages(path))
            self.setCurrentWidget(self.pages)
        elif ext == ".docx":
            self.pages.clear()
            self.sheet.set_html(docx_to_html(path))
            self.setCurrentWidget(self.sheet)
        else:
            self.pages.clear()
            self.sheet.set_text(_decode(path.read_bytes()).replace("\r\n", "\n"))
            self.setCurrentWidget(self.sheet)

    def clear(self):
        self.pages.clear()

    def set_locked(self, locked: bool):
        self._lock.locked = locked
        policy = Qt.ScrollBarAlwaysOff if locked else Qt.ScrollBarAsNeeded
        for w in (self.pages, self.sheet):
            w.setVerticalScrollBarPolicy(policy)
