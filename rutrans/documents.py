"""Read a document, translate its Russian text, and write an English copy."""
from __future__ import annotations

import html
import re
import threading
from pathlib import Path
from typing import Callable

from .engine import CYRILLIC, Translator

IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
SUPPORTED = {".docx", ".pdf", ".txt", ".md"} | IMAGES

# progress(done, total) during translation; documents that need OCR first report
# progress(done_pages, total_pages, "ocr").
Progress = Callable[..., None]


def output_path(src: Path, out_dir: Path | None, ext: str | None = None) -> Path:
    out_dir = out_dir or src.parent
    ext = ext or src.suffix
    base = out_dir / f"{src.stem}_EN{ext}"
    n = 2
    while base.exists():
        base = out_dir / f"{src.stem}_EN ({n}){ext}"
        n += 1
    return base


def translate_file(tr: Translator, src: Path, out_dir: Path | None = None,
                   pdf_mode: str = "pdf", progress: Progress | None = None,
                   cancel: threading.Event | None = None) -> Path:
    """Translate one file and return the path of the English copy.

    pdf_mode: "pdf" keeps the page layout (text replaced in place);
              "docx" writes the translated text into a Word document.
    """
    src = Path(src)
    ext = src.suffix.lower()
    if ext == ".docx":
        return _docx(tr, src, out_dir, progress, cancel)
    if ext == ".pdf":
        import pymupdf
        return _pdf(tr, pymupdf.open(str(src)), src, out_dir, pdf_mode, progress, cancel)
    if ext in IMAGES:
        import pymupdf
        img = pymupdf.open(str(src))          # multi-page TIFFs give several pages
        pdf = pymupdf.open("pdf", img.convert_to_pdf())
        img.close()
        return _pdf(tr, pdf, src, out_dir, pdf_mode, progress, cancel, out_ext=".pdf")
    if ext in (".txt", ".md"):
        return _txt(tr, src, out_dir, progress, cancel)
    raise ValueError(f"Unsupported file type: {src.suffix}")


# ---------------------------------------------------------------- helpers

def unwrap_lines(lines: list[str]) -> str:
    """Join hard-wrapped lines into one paragraph, fixing hyphenated word breaks."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif re.search(r"[А-Яа-яЁёA-Za-z]-$", out) and line[:1].islower():
            out = out[:-1] + line  # "перево-" + "дчик" -> "переводчик"
        else:
            out += " " + line
    return out


# ---------------------------------------------------------------- TXT

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig",):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    # Legacy Russian encodings: pick the one that yields the most common Russian letters.
    best, best_score = data.decode("cp1251", errors="replace"), -1
    for enc in ("cp1251", "koi8-r", "cp866"):
        t = data.decode(enc, errors="replace")
        score = sum(t.count(c) for c in "оеаинтс")
        if score > best_score:
            best, best_score = t, score
    return best


def _txt(tr, src, out_dir, progress, cancel):
    text = _decode(src.read_bytes()).replace("\r\n", "\n").replace("\r", "\n")
    # Paragraphs are separated by blank lines; lines inside a paragraph are unwrapped
    # unless they look like list items or short lines (headings, addresses...).
    blocks = re.split(r"(\n\s*\n)", text)
    paras: list[str] = []
    for i, block in enumerate(blocks):
        if i % 2 == 1:  # separator
            paras.append(block)
            continue
        lines = block.split("\n")
        listy = any(re.match(r"\s*([-•*–—]|\d+[.)])\s", ln) for ln in lines[1:])
        short = all(len(ln.strip()) < 40 for ln in lines)
        paras.append(block if (listy or short or len(lines) == 1) else unwrap_lines(lines))
    translated = tr.translate_texts(paras, progress, cancel)
    dst = output_path(src, out_dir)
    dst.write_text("".join(translated), encoding="utf-8")
    return dst


# ---------------------------------------------------------------- DOCX

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % W_NS


def _paragraph_texts(root) -> list[tuple[object, list]]:
    """For each w:p, the w:t elements that belong to it directly (not to nested text boxes)."""
    result = []
    for p in root.iter(W + "p"):
        ts = []
        for t in p.iter(W + "t"):
            anc = t.getparent()
            while anc is not None and anc.tag != W + "p":
                anc = anc.getparent()
            if anc is p:
                ts.append(t)
        if ts:
            result.append((p, ts))
    return result


def _set_english_lang(root):
    for lang in root.iter(W + "lang"):
        for attr in (W + "val", W + "eastAsia", W + "bidi"):
            v = lang.get(attr)
            if v and v.lower().startswith("ru"):
                lang.set(attr, "en-US")


def _docx(tr, src, out_dir, progress, cancel):
    import docx
    from lxml import etree

    d = docx.Document(str(src))
    roots = []          # (root element, setter or None)
    for part in d.part.package.iter_parts():
        name = str(part.partname)
        if not re.match(r"/word/(document|header\d*|footer\d*|footnotes|endnotes|comments"
                        r"|styles)\.xml$", name):
            continue
        if hasattr(part, "element"):
            roots.append((part.element, None))
        else:  # parts python-docx does not model (footnotes, endnotes, comments)
            root = etree.fromstring(part.blob)
            roots.append((root, part))

    items = []  # (list of w:t, original text)
    for root, _ in roots:
        for _p, ts in _paragraph_texts(root):
            text = "".join(t.text or "" for t in ts)
            if CYRILLIC.search(text):
                items.append((ts, text))

    translated = tr.translate_texts([text for _, text in items], progress, cancel)

    for (ts, _), new in zip(items, translated):
        # Put the translation in the run with the most text (so the paragraph keeps its main
        # formatting, not that of a short bold label like "Дата:"), and empty the rest.
        # Hyperlinks, fields and images stay where they are.
        first = max(ts, key=lambda t: len((t.text or "").strip()))
        for t in ts:
            t.text = ""
        first.text = new
        first.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    for root, part in roots:
        _set_english_lang(root)
        if part is not None:
            part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                                        standalone=True)
    dst = output_path(src, out_dir)
    d.save(str(dst))
    return dst


# ---------------------------------------------------------------- PDF

def _side_by_side(lines) -> bool:
    """True if two lines of a block share a row but not columns (i.e. table cells)."""
    boxes = [ln["bbox"] for ln in lines]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            v = min(a[3], b[3]) - max(a[1], b[1])
            if v > 0.5 * min(a[3] - a[1], b[3] - b[1]) and (a[2] <= b[0] or b[2] <= a[0]):
                return True
    return False


def _pdf_blocks(page):
    """Text units of a page (paragraphs, or table cells): (rect, text, size, colour, bold, bg).
    bg is None for real text (it is removed with a redaction) and an RGB fill for OCR text."""
    import pymupdf as fitz

    def unit(lines_spans):
        spans = [s for ln in lines_spans for s in ln if s["text"].strip()]
        text = unwrap_lines(["".join(s["text"] for s in ln) for ln in lines_spans])
        if not spans:
            return None
        sizes = sorted(s["size"] for s in spans)
        size = sizes[len(sizes) // 2]
        main = max(spans, key=lambda s: len(s["text"]))
        bold = bool(main["flags"] & 16) or "bold" in main["font"].lower()
        rect = fitz.Rect()
        for s in spans:
            rect |= fitz.Rect(s["bbox"])
        return (rect, text, size, main["color"], bold, None)

    def cells(line):
        """Split a line's spans where there is a wide horizontal gap (table columns)."""
        groups, cur = [], []
        for s in line["spans"]:
            if cur and s["bbox"][0] - cur[-1]["bbox"][2] > max(8, s["size"] * 1.5):
                groups.append(cur)
                cur = []
            cur.append(s)
        if cur:
            groups.append(cur)
        return groups

    def split_span(s):
        """MuPDF merges same-style text on a line into one span (adding spaces for gaps);
        cut it into pieces wherever the characters are far apart."""
        gap = max(8, s["size"] * 1.5)
        pieces, cur, last_x1 = [], [], None
        for ch in s["chars"]:
            if ch["c"].strip() and cur and last_x1 is not None and ch["bbox"][0] - last_x1 > gap:
                pieces.append(cur)
                cur = []
            cur.append(ch)
            if ch["c"].strip():
                last_x1 = ch["bbox"][2]
        if cur:
            pieces.append(cur)
        out = []
        for chars in pieces:
            r = fitz.Rect()
            for ch in chars:
                if ch["c"].strip():
                    r |= fitz.Rect(ch["bbox"])
            out.append({**s, "text": "".join(ch["c"] for ch in chars).replace("\xa0", " "),
                        "bbox": tuple(r) if not r.is_empty else s["bbox"]})
        return out

    out = []
    data = page.get_text("rawdict", flags=fitz.TEXTFLAGS_TEXT)
    for b in data["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            ln["spans"] = [p for s in ln["spans"] for p in split_span(s)]
    for b in data["blocks"]:
        if b.get("type") != 0:
            continue
        split = [cells(ln) for ln in b["lines"]]
        if any(len(g) > 1 for g in split) or _side_by_side(b["lines"]):
            units = [unit([g]) for groups in split for g in groups]   # table-like: per cell
        else:
            units = [unit([ln["spans"] for ln in b["lines"]])]        # normal paragraph
        out.extend(u for u in units if u)
    return out


def _needs_ocr(page) -> bool:
    """A page with (almost) no text layer but with images is a scan."""
    return len(page.get_text().strip()) < 20 and bool(page.get_images())


def _paper_colour(img, x0, y0, x1, y1):
    """Typical background colour in a thin ring around a box: ignore dark pixels (text, table
    rules) and the brightest specks (scanner noise), average the rest."""
    import numpy as np
    h, w = img.shape[:2]
    X0, Y0 = max(int(x0) - 6, 0), max(int(y0) - 6, 0)
    X1, Y1 = min(int(x1) + 6, w), min(int(y1) + 6, h)
    strips = [img[Y0:Y0 + 4, X0:X1], img[max(Y1 - 4, 0):Y1, X0:X1],
              img[Y0:Y1, X0:X0 + 4], img[Y0:Y1, max(X1 - 4, 0):X1]]
    px = np.concatenate([s.reshape(-1, 3) for s in strips if s.size]).astype(np.float32)
    if not len(px):
        return (1.0, 1.0, 1.0)
    lum = px.mean(axis=1)
    lo, hi = np.percentile(lum, 50), np.percentile(lum, 95)
    sel = px[(lum >= lo) & (lum <= hi)]
    if not len(sel):
        sel = px
    return tuple(float(c) / 255 for c in sel.mean(axis=0))


def _render_for_ocr(page):
    """Page image for OCR (PyMuPDF is not thread-safe: always called on the main thread)."""
    import numpy as np
    import pymupdf as fitz

    from . import ocr
    pix = page.get_pixmap(dpi=ocr.OCR_DPI, colorspace=fitz.csRGB, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()


def _ocr_job(img, want_png: bool):
    """Runs in a worker thread: OCR, and the straightened image if the page was tilted."""
    import numpy as np

    from . import ocr
    lines, angle = ocr.ocr_page(img)
    png = None
    if angle:
        img = np.ascontiguousarray(ocr.deskew(img, angle))
        if want_png:
            # JPEG, not PNG: scans are noisy and PNG made pages of ~9 MB each.
            import cv2
            gray = bool((img[:, :, 0] == img[:, :, 1]).all() and (img[:, :, 1] == img[:, :, 2]).all())
            src = img[:, :, 0] if gray else img[:, :, ::-1]
            ok, buf = cv2.imencode(".jpg", src, [cv2.IMWRITE_JPEG_QUALITY, 85])
            png = buf.tobytes() if ok else None
    return lines, img, png


def _ocr_units(page, lines, img, png):
    """Text units (same shape as _pdf_blocks) from OCR lines of a scanned page."""
    import pymupdf as fitz

    from . import ocr

    scale = 72 / ocr.OCR_DPI
    if png is not None and page.rotation == 0:
        # Show the straightened scan, so the English boxes line up with it.
        page.insert_image(page.rect, stream=png, overlay=True)
    if not lines:
        return []
    all_h = sorted(ln[0][3] - ln[0][1] for ln in lines)
    body_h = all_h[len(all_h) // 2]
    units = []
    for para in ocr.group_paragraphs(lines):
        x0 = min(ln[0][0] for ln in para)
        y0 = min(ln[0][1] for ln in para)
        x1 = max(ln[0][2] for ln in para)
        y1 = max(ln[0][3] for ln in para)
        heights = sorted(ln[0][3] - ln[0][1] for ln in para)
        h = heights[len(heights) // 2]
        if 0.7 * body_h <= h <= 1.35 * body_h:
            h = body_h  # ordinary text: use one size for the whole page
        size = max(5.0, h * scale / 1.3)
        bg = _paper_colour(img, x0, y0, x1, y1)
        rect = fitz.Rect(x0, y0, x1, y1) * scale * page.derotation_matrix
        text = unwrap_lines([ln[1] for ln in para])
        units.append((rect, text, size, 0x111111, False, bg))
    return units


def _ocr_pages(doc, pages, scan_pages, mode, progress, cancel):
    """OCR scanned pages, several at once (ocr.WORKERS), keeping a few pages in flight.
    Reports progress(done_pages, total_pages, "ocr", chars=characters_read_so_far)."""
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutTimeout

    from . import ocr
    from .engine import Cancelled

    total, done, chars = len(scan_pages), 0, 0
    if progress:
        progress(0, total, "ocr", chars=0)
    todo = iter(scan_pages)
    pending: deque = deque()
    with ThreadPoolExecutor(max_workers=ocr.WORKERS) as ex:
        def submit_next():
            i = next(todo, None)
            if i is not None:
                pending.append((i, ex.submit(_ocr_job, _render_for_ocr(doc[i]), mode == "pdf")))

        for _ in range(ocr.WORKERS + 1):
            submit_next()
        try:
            while pending:
                i, fut = pending[0]
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    try:
                        lines, img, png = fut.result(timeout=0.25)
                        break
                    except FutTimeout:
                        continue
                pending.popleft()
                submit_next()
                pages[i] = _ocr_units(doc[i], lines, img, png)
                done += 1
                chars += sum(len(u[1]) for u in pages[i])
                if progress:
                    progress(done, total, "ocr", chars=chars)
        except BaseException:
            for _, f in pending:
                f.cancel()
            doc.close()
            raise


def _pdf(tr, doc, src, out_dir, mode, progress, cancel, out_ext=None):
    import pymupdf as fitz

    from . import ocr
    from .engine import Cancelled

    pages = [_pdf_blocks(page) for page in doc]
    scan_pages = [i for i, page in enumerate(doc) if not pages[i] and _needs_ocr(page)]
    if scan_pages:
        if not ocr.available():
            doc.close()
            raise RuntimeError("This document is scanned and the OCR models are missing.")
        _ocr_pages(doc, pages, scan_pages, mode, progress, cancel)

    if not any(CYRILLIC.search(u[1]) for units in pages for u in units):
        has_text = any(units for units in pages)
        doc.close()
        raise RuntimeError("No Russian text was found in this document." if has_text else
                           "No text was found in this document (not even with OCR).")

    # Non-Russian text (numbers, English) passes through translate_texts unchanged.
    flat = tr.translate_texts([u[1] for units in pages for u in units], progress, cancel)
    it = iter(flat)
    pages = [[(*u, next(it)) for u in units] for units in pages]

    if mode == "docx":
        return _pdf_to_docx(pages, src, out_dir, doc)

    for page, all_units in zip(doc, pages):
        units = [u for u in all_units if CYRILLIC.search(u[1])]
        if not units:
            continue
        right_margin = max(page.rect.x1 - 36, max(u[0].x1 for u in all_units))
        text_units = [u for u in units if u[5] is None]
        if text_units:
            for rect, *_ in text_units:
                page.add_redact_annot(rect, fill=False)
            kwargs = {"images": fitz.PDF_REDACT_IMAGE_NONE}
            if hasattr(fitz, "PDF_REDACT_LINE_ART_NONE"):
                kwargs["graphics"] = fitz.PDF_REDACT_LINE_ART_NONE
            page.apply_redactions(**kwargs)
        for rect, _text, size, color, bold, bg, new in units:
            if bg is not None:  # scanned text: paint over it with the paper colour
                page.draw_rect(rect, color=None, fill=bg, overlay=True)
            css = ("* {font-family: sans-serif; font-size: %.1fpt; color: #%06x; "
                   "line-height: 1.15; font-weight: %s;}" % (size, color, "bold" if bold else "normal"))
            # English is often longer: let the box grow right up to the next text on the
            # same row (or the page's text margin), and a little downwards.
            limit = right_margin
            for other in all_units:
                o = other[0]
                if o.x0 >= rect.x1 - 1 and min(o.y1, rect.y1) - max(o.y0, rect.y0) > 0:
                    limit = min(limit, o.x0 - 6)
            box = fitz.Rect(rect.x0, rect.y0, max(rect.x1 + 2, limit),
                            min(rect.y1 + size * 0.5, page.rect.y1))
            page.insert_htmlbox(box, html.escape(new), css=css, scale_low=0)
    dst = output_path(src, out_dir, out_ext)
    _share_fonts(doc)
    doc.save(str(dst), garbage=3, deflate=True)
    doc.close()
    return dst


def _share_fonts(doc):
    """Every insert_htmlbox() call embeds its own copy of the same font file (~33 KB each, so
    a long document grew by tens of MB). Point all identical copies at one; the unused ones
    are dropped when saving with garbage collection. Rendering is unchanged."""
    import hashlib

    first: dict[str, int] = {}
    for xref in range(1, doc.xref_length()):
        for key in ("FontFile", "FontFile2", "FontFile3"):
            kind, val = doc.xref_get_key(xref, key)
            if kind != "xref":
                continue
            stream = int(val.split()[0])
            digest = hashlib.sha1(doc.xref_stream_raw(stream) or b"").hexdigest()
            keep = first.setdefault(digest, stream)
            if keep != stream:
                doc.xref_set_key(xref, key, f"{keep} 0 R")


def _pdf_to_docx(pages, src, out_dir, pdf):
    """Write translated PDF text to Word, in reading order; table rows become tab-separated."""
    import docx
    from docx.shared import Pt

    pdf.close()
    out = docx.Document()
    for pno, units in enumerate(pages):
        if pno:
            out.add_page_break()
        # Group units into visual rows (units whose vertical extents overlap).
        rows: list[list] = []
        for u in sorted(units, key=lambda u: (u[0].y0, u[0].x0)):
            r = u[0]
            if rows:
                last = rows[-1][-1][0]
                centre_gap = abs((r.y0 + r.y1) / 2 - (last.y0 + last.y1) / 2)
                if centre_gap < 0.4 * min(r.height, last.height):
                    rows[-1].append(u)
                    continue
            rows.append([u])
        for row in rows:
            row.sort(key=lambda u: u[0].x0)
            para = out.add_paragraph()
            for i, (_rect, _text, size, _color, bold, _bg, new) in enumerate(row):
                run = para.add_run(("\t" if i else "") + new)
                run.bold = bold
                if size >= 14:
                    run.font.size = Pt(min(size, 28))
    dst = output_path(src, out_dir, ".docx")
    out.save(str(dst))
    return dst
