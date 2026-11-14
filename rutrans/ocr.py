"""Offline OCR for scanned pages (RapidOCR models: PP-OCRv5 detector + East-Slavic recognizer).

Speed notes (measured on a 4-core laptop, dense A4 page):
- recognition is ~90% of the time and scales linearly with the amount of text;
- detection runs once per page; the page skew is measured from those same boxes;
- several pages are OCR'd at once, each on its own engine with a share of the CPU cores
  (2 engines x 2 threads is ~40% faster than 1 engine x 8 threads);
- long lines are cut at word gaps before recognition: same speed, better accuracy.
"""
from __future__ import annotations

import math
import os
import queue
import re
import threading

from .engine import resource_dir

OCR_DPI = 200
SPLIT_RATIO = 16          # cut text lines wider than 16 x their height at word gaps
MIN_SCORE = 0.5


def _cpu_plan() -> tuple[int, int]:
    """(parallel OCR engines, threads per engine)."""
    try:
        import psutil
        cores = psutil.cpu_count(logical=False) or 0
    except Exception:  # noqa: BLE001
        cores = 0
    if not cores:
        cores = max(1, (os.cpu_count() or 2) // 2)
    workers = 2 if cores >= 4 else 1
    return workers, max(1, cores // workers)


WORKERS, THREADS = _cpu_plan()
_pool: "queue.Queue | None" = None
_pool_lock = threading.Lock()

# Latin letters OCR confuses with Cyrillic ones ("Hopмa" -> "Норма").
_LAT2CYR = str.maketrans("AaBCcEeHKMOoPpTXxyY", "АаВСсЕеНКМОоРрТХхуУ")
_HAS_CYR = re.compile(r"[А-Яа-яЁё]")
_HAS_LAT = re.compile(r"[A-Za-z]")


def model_dir():
    return resource_dir() / "models" / "ocr"


def available() -> bool:
    d = model_dir()
    return (d / "ch_PP-OCRv5_det_mobile.onnx").exists() and (d / "eslav_PP-OCRv5_rec_mobile.onnx").exists()


def _new_engine():
    from rapidocr import RapidOCR
    d = model_dir()
    eng = RapidOCR(params={
        "Global.use_cls": False,
        "Global.log_level": "error",
        "Det.model_path": str(d / "ch_PP-OCRv5_det_mobile.onnx"),
        "Det.limit_type": "max",
        "Det.limit_side_len": 1280,
        "Rec.model_path": str(d / "eslav_PP-OCRv5_rec_mobile.onnx"),
        "Rec.rec_batch_num": 6,
        "EngineConfig.onnxruntime.intra_op_num_threads": THREADS,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.enable_cpu_mem_arena": True,
    })
    return eng._load_det_model(), eng._load_rec_model()


def _engines() -> "queue.Queue":
    """A pool of WORKERS (detector, recognizer) pairs; each is used by one page at a time."""
    global _pool
    with _pool_lock:
        if _pool is None:
            q = queue.Queue()
            for _ in range(WORKERS):
                q.put(_new_engine())
            _pool = q
        return _pool


def warm_up():
    """Load the models and run them once (first inference is slow)."""
    import numpy as np
    img = np.full((120, 900, 3), 255, np.uint8)
    img[50:70, 40:860] = 0
    pool = _engines()
    pairs = [pool.get() for _ in range(WORKERS)]
    try:
        for det, rec in pairs:
            _recognize(img, det, rec)
    finally:
        for p in pairs:
            pool.put(p)


_LOOKALIKE_WORD = re.compile(r"^[AaBCcEeHKMOoPpTXxyYm]+$")


def fix_text(text: str, russian_context: bool = False) -> str:
    """Repair Latin look-alike letters inside Russian words.

    Mixed words ("Hopмa") are always fixed. Fully Latin words ("Hopma") are fixed only on
    Russian lines/pages, only if every letter has a Cyrillic twin and the word has a lowercase
    letter (so acronyms like CO or TX are left alone)."""
    def word(m):
        w = m.group(0)
        if _HAS_CYR.search(w) and _HAS_LAT.search(w):
            return w.translate(_LAT2CYR).replace("m", "м")
        if (russian_context and len(w) >= 3 and _LOOKALIKE_WORD.match(w)
                and any(c.islower() for c in w)):
            return w.translate(_LAT2CYR).replace("m", "м")
        return w
    text = re.sub(r"\w+", word, text)
    return text.replace("°С", "°C")


def skew_from_boxes(boxes) -> float:
    """Text-line angle in degrees (image coordinates) from detected line quadrilaterals."""
    if boxes is None or len(boxes) == 0:
        return 0.0
    angles = []
    for b in boxes:
        (x0, y0), (x1, y1) = b[0], b[1]           # top-left, top-right
        x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
        w, h = math.hypot(x1 - x0, y1 - y0), math.hypot(b[3][0] - x0, b[3][1] - y0)
        if w > 5 * max(h, 1):
            angles.append(math.degrees(math.atan2(y1 - y0, x1 - x0)))
    if len(angles) < 2:
        return 0.0
    angles.sort()
    return angles[len(angles) // 2]


def deskew(rgb, angle: float):
    """Rotate the image so that text lines become horizontal; the border is paper colour."""
    import cv2
    import numpy as np
    h, w = rgb.shape[:2]
    corners = np.array([rgb[2, 2], rgb[2, w - 3], rgb[h - 3, 2], rgb[h - 3, w - 3]])
    paper = tuple(int(c) for c in corners.max(axis=0))
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(rgb, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=paper)


def split_line(crop, max_ratio: int = SPLIT_RATIO):
    """Cut a text-line image at blank columns (word gaps) into pieces at most max_ratio x
    its height. The recogniser reads short pieces more accurately than very long lines."""
    import cv2
    h, w = crop.shape[:2]
    limit = int(max_ratio * h)
    if w <= limit or h < 4:
        return [crop]
    g = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    blank = (bw > 0).sum(axis=0) <= max(1, int(0.02 * h))
    gaps, x = [], 0
    while x < w:                       # centres of blank runs wider than a letter gap
        if blank[x]:
            s = x
            while x < w and blank[x]:
                x += 1
            if x - s >= 0.2 * h and s > 0 and x < w:
                gaps.append((s + x) // 2)
        else:
            x += 1
    pieces, start = [], 0
    while w - start > limit:
        cands = [c for c in gaps if start + 0.3 * limit < c <= start + limit]
        if not cands:
            break
        pieces.append(crop[:, start:cands[-1]])
        start = cands[-1]
    pieces.append(crop[:, start:])
    return pieces


def _recognize(rgb, det, rec):
    """Detection + recognition. Returns ([4-point boxes], [texts], [scores])."""
    import copy

    from rapidocr.ch_ppocr_rec.typings import TextRecInput
    from rapidocr.utils.process_img import get_rotate_crop_image

    d = det(rgb)
    if d.boxes is None or len(d.boxes) == 0:
        return [], [], []
    boxes = list(d.boxes)
    # get_rotate_crop_image straightens each (possibly tilted) line on its own.
    parts = [split_line(get_rotate_crop_image(rgb, copy.deepcopy(b))) for b in boxes]
    flat = [p for ps in parts for p in ps]
    r = rec(TextRecInput(img=flat))
    it = iter(zip(r.txts, r.scores))
    texts, scores = [], []
    for ps in parts:
        got = [next(it) for _ in ps]
        texts.append(" ".join(t.strip() for t, _ in got if t.strip()))
        chars = [max(len(t), 1) for t, _ in got]
        scores.append(sum(float(s) * c for (_, s), c in zip(got, chars)) / sum(chars))
    return boxes, texts, scores


def ocr_page(rgb):
    """OCR one page image (RGB numpy array); thread-safe, uses a free engine from the pool.

    Returns (lines, angle): lines are ((x0, y0, x1, y1), text, score) in the coordinates of
    the page *after* straightening it by `angle` degrees (see deskew()); angle is 0 when the
    page is already straight."""
    import cv2
    import numpy as np

    pool = _engines()
    pair = pool.get()
    try:
        boxes, texts, scores = _recognize(rgb, *pair)
    finally:
        pool.put(pair)
    angle = skew_from_boxes(boxes)
    if not 0.25 < abs(angle) < 15:
        angle = 0.0
    m = None
    if angle:
        h, w = rgb.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)   # same as deskew()
    raw = [(b, t, s) for b, t, s in zip(boxes, texts, scores) if t and s >= MIN_SCORE]
    alltext = " ".join(t for _, t, _ in raw)
    russian_page = len(_HAS_CYR.findall(alltext)) > len(_HAS_LAT.findall(alltext))
    lines = []
    for box, txt, score in raw:
        pts = np.asarray(box, dtype=np.float64)
        if m is not None:
            pts = pts @ m[:, :2].T + m[:, 2]
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        lines.append(((float(x0), float(y0), float(x1), float(y1)),
                      fix_text(txt, russian_page), score))
    return merge_row_pieces(lines), angle


# Pieces on one row closer than this x line height are one line of text. Measured on a
# justified 76-page scan: word gaps up to 4.7 x (99% under 2.9 x); table columns 4.3 x and more.
ROW_GAP = 3.5


def merge_row_pieces(lines, max_gap: float = ROW_GAP):
    """Join pieces of the same text line that the detector cut apart.

    In fully justified text the spaces between words can be very wide, and the detector then
    returns one line as several boxes. Translated one by one, those pieces lose their context
    ("Россия есть демократическое" -> "Russia Eating democratic"). Pieces on the same row
    are joined when the gap between them is below max_gap x the line height; real table
    columns are much further apart and stay separate."""
    rows: list[list] = []
    for ln in sorted(lines, key=lambda ln: ((ln[0][1] + ln[0][3]) / 2, ln[0][0])):
        (x0, y0, x1, y1), cy = ln[0], (ln[0][1] + ln[0][3]) / 2
        h = y1 - y0
        for row in rows:
            r = row[-1][0]
            rh = r[3] - r[1]
            if abs((r[1] + r[3]) / 2 - cy) < 0.4 * min(h, rh):
                row.append(ln)
                break
        else:
            rows.append([ln])
    out = []
    for row in rows:
        row.sort(key=lambda ln: ln[0][0])
        cur = row[0]
        for ln in row[1:]:
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = cur[0], ln[0]
            h = min(ay1 - ay0, by1 - by0)
            if bx0 - ax1 < max_gap * h:
                na, nb = max(len(cur[1]), 1), max(len(ln[1]), 1)
                cur = ((ax0, min(ay0, by0), max(ax1, bx1), max(ay1, by1)),
                       f"{cur[1]} {ln[1]}", (cur[2] * na + ln[2] * nb) / (na + nb))
            else:
                out.append(cur)
                cur = ln
        out.append(cur)
    return out


def ocr_image(rgb):
    """OCR an image; returns only the lines (see ocr_page)."""
    return ocr_page(rgb)[0]


def group_paragraphs(lines):
    """Merge OCR text lines into paragraphs: lines stacked closely, left-aligned, similar height."""
    # Detector boxes are padded (they overlap their neighbours), so compare line centres.
    lines = sorted(lines, key=lambda ln: ((ln[0][1] + ln[0][3]) / 2, ln[0][0]))

    def same_row(a, b):
        ca, cb = (a[1] + a[3]) / 2, (b[1] + b[3]) / 2
        return (abs(ca - cb) < 0.4 * min(a[3] - a[1], b[3] - b[1])
                and (a[2] <= b[0] or b[2] <= a[0]))

    # Lines that share their row with another line are table cells: keep them separate.
    cell = [any(same_row(a[0], b[0]) for b in lines if b is not a) for a in lines]
    paras: list[list] = []
    para_is_cell: list[bool] = []
    for ln, is_cell in zip(lines, cell):
        x0, y0, x1, y1 = ln[0]
        h = y1 - y0
        target = None
        for p, p_cell in zip(reversed(paras[-6:]), reversed(para_is_cell[-6:])):
            if is_cell or p_cell:
                continue
            px0, py0, px1, py1 = p[-1][0]
            ph = py1 - py0
            pitch = (y0 + y1) / 2 - (py0 + py1) / 2
            # Line pitch inside a paragraph is ~0.6-1.0 x the (padded) line-box height;
            # the gap between paragraphs is usually 1.5 x or more.
            if (0.3 * min(h, ph) < pitch < 1.3 * max(h, ph) and abs(x0 - px0) < 2.5 * h
                    and 0.7 < h / ph < 1.4 and min(x1, px1) - max(x0, px0) > 0):
                target = p
                break
        if target is not None:
            target.append(ln)
        else:
            paras.append([ln])
            para_is_cell.append(is_cell)
    return paras
