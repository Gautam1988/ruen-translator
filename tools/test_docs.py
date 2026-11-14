"""Translate the sample documents and print what came out."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import docx  # noqa: E402
import pymupdf  # noqa: E402

from rutrans.documents import translate_file  # noqa: E402
from rutrans.engine import Glossary, Translator, split_sentences  # noqa: E402

samples = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
out = samples / "out"
out.mkdir(exist_ok=True)
for f in out.iterdir():
    if f.name != "glossary.txt":
        f.unlink()

print(split_sentences("Проверка проведена в марте 2024 г. Отклонений нет. «Отлично!» — сказал он."))
tr = Translator()
print(tr.translate("Рекомендуется заменить насосы, т. к. их ресурс близок к исчерпанию."))

gloss = out / "glossary.txt"
gloss.write_text("первый контур = primary circuit\nактивная зона = reactor core\n"
                 "теплоноситель = coolant\nсистема охлаждения = cooling system\n"
                 "значение = value\nнорма = limit\n", encoding="utf-8")
tr.glossary = Glossary(gloss)
print(tr.translate("Расход теплоносителя в первом контуре соответствует норме. "
                   "Температура на выходе из активной зоны не превышала 85 °C."))

jobs = [("report_ru.docx", "pdf"), ("report_ru.txt", "pdf"), ("report_ru.pdf", "pdf"),
        ("report_ru.pdf", "docx"), ("scan_ru.pdf", "pdf"), ("scan_ru.pdf", "docx"),
        ("scan_ru.png", "pdf"), ("scan_noisy_ru.jpg", "docx"), ("scan_noisy_ru.jpg", "pdf")]
if len(sys.argv) > 2:
    jobs = [j for j in jobs if sys.argv[2] in j[0]]
for name, mode in jobs:
    t0 = time.perf_counter()
    dst = translate_file(tr, samples / name, out, pdf_mode=mode)
    print(f"\n=== {name} ({mode}) -> {dst.name}  [{time.perf_counter() - t0:.1f}s]")
    if dst.suffix == ".docx":
        d = docx.Document(str(dst))
        print("header:", d.sections[0].header.paragraphs[0].text)
        for p in d.paragraphs:
            if p.text.strip():
                print(f"  [{p.style.name}] {p.text}")
        for t in d.tables:
            for row in t.rows:
                print("  | " + " | ".join(c.text for c in row.cells))
    elif dst.suffix == ".txt":
        print(dst.read_text(encoding="utf-8"))
    else:
        doc = pymupdf.open(str(dst))
        print(doc[0].get_text())
        doc[0].get_pixmap(dpi=80).save(str(out / f"{dst.stem}_page1.png"))
