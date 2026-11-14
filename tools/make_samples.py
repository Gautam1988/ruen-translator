"""Create small Russian sample documents (DOCX, PDF, TXT) for testing."""
import sys
import textwrap
from pathlib import Path

import docx
import pymupdf as fitz
out = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
out.mkdir(exist_ok=True)

TITLE = "Отчёт о проверке системы охлаждения"
PARAS = [
    "Настоящий отчёт подготовлен по результатам плановой проверки системы охлаждения "
    "исследовательского реактора, проведённой в марте 2024 г. Проверка выполнялась "
    "группой инженеров под руководством А. В. Петрова.",
    "В ходе испытаний было установлено, что расход теплоносителя в первом контуре "
    "соответствует проектным значениям. Температура на выходе из активной зоны не "
    "превышала 85 °C. Отклонений от норм безопасности не обнаружено.",
    "Рекомендуется заменить два насоса до конца года, т. к. их ресурс близок к исчерпанию. "
    "Кроме того, необходимо обновить программное обеспечение системы контроля.",
]
TABLE = [("Параметр", "Значение", "Норма"),
         ("Давление, МПа", "0,35", "до 0,4"),
         ("Расход, м³/ч", "120", "110–130"),
         ("Температура, °C", "85", "не более 90")]

# DOCX
d = docx.Document()
d.add_heading(TITLE, level=1)
p = d.add_paragraph()
p.add_run("Дата: ").bold = True
p.add_run("15 марта 2024 года")
for text in PARAS:
    d.add_paragraph(text)
t = d.add_table(rows=len(TABLE), cols=3)
t.style = "Table Grid"
for r, row in enumerate(TABLE):
    for c, val in enumerate(row):
        t.cell(r, c).text = val
d.add_paragraph("Выводы", style="Heading 2")
d.add_paragraph("Система работает надёжно.", style="List Bullet")
d.add_paragraph("Требуется плановая замена оборудования.", style="List Bullet")
d.sections[0].header.paragraphs[0].text = "Для служебного пользования"
d.save(out / "report_ru.docx")

# TXT (cp1251, hard-wrapped lines to test unwrapping)
txt = TITLE + "\n\n" + "\n\n".join(
    textwrap.fill(p, 70) for p in PARAS) + "\n"
(out / "report_ru.txt").write_bytes(txt.encode("cp1251"))

# PDF (two pages, real text layer)
font = r"C:\Windows\Fonts\arial.ttf"
bold = r"C:\Windows\Fonts\arialbd.ttf"
doc = fitz.open()
for page_no in range(2):
    page = doc.new_page()
    page.insert_font(fontname="ar", fontfile=font)
    page.insert_font(fontname="arb", fontfile=bold)
    y = 60
    page.insert_textbox(fitz.Rect(50, y, 545, y + 40), TITLE + (f" (стр. {page_no + 1})"),
                        fontname="arb", fontsize=16)
    y += 50
    for text in PARAS:
        page.insert_textbox(fitz.Rect(50, y, 545, y + 90), text, fontname="ar", fontsize=11)
        y += 95
    for row in TABLE:
        for c, val in enumerate(row):
            page.insert_textbox(fitz.Rect(50 + c * 165, y, 210 + c * 165, y + 20), val,
                                fontname="arb" if row is TABLE[0] else "ar", fontsize=10)
        page.draw_line((50, y + 17), (545, y + 17), color=(0.6, 0.6, 0.6))
        y += 22
doc.save(out / "report_ru.pdf")

# "Scanned" PDF: page rendered to a slightly rotated greyscale image, no text layer.
pix = doc[0].get_pixmap(dpi=200, colorspace=fitz.csGRAY)
pix.save(out / "scan_ru.png")
scan = fitz.open()
pg = scan.new_page(width=doc[0].rect.width, height=doc[0].rect.height)
pg.insert_image(pg.rect, filename=str(out / "scan_ru.png"), rotate=0)
scan.save(out / "scan_ru.pdf")

# Rougher "phone/office scan": 150 dpi, tilted 1.2 degrees, noise, JPEG.
import cv2  # noqa: E402
import numpy as np  # noqa: E402

pix = doc[0].get_pixmap(dpi=150, colorspace=fitz.csGRAY)
img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
rot = cv2.getRotationMatrix2D((pix.width / 2, pix.height / 2), 1.2, 1.0)
img = cv2.warpAffine(img, rot, (pix.width, pix.height), borderValue=245)
rng = np.random.default_rng(1)
img = np.clip(img.astype(np.int16) - 12 + rng.normal(0, 14, img.shape), 0, 255).astype(np.uint8)
cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tofile(str(out / "scan_noisy_ru.jpg"))
print("Samples written to", out.resolve())
