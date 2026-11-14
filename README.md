# RuEn Translator

Offline Russian → English document translator for Windows. Nothing leaves your computer.

## Using it

1. **Upload** — drag a document onto the window, or click *Upload your document*.
2. **Preview** — the Russian document is shown; scroll through it. For PDFs and scans, choose
   *English PDF — same page layout* or *English Word document — editable text*. Click **Translate**.
3. **Translate** — a progress bar shows what is happening (reading scanned pages, then
   translating sentences) and the estimated time left. *Cancel* goes back to the preview.
4. **Download** — the English document is shown; scroll through it, then click **Download**
   to save it (suggested name: `<name>_EN.<ext>` next to the original). *Translate another*
   starts over.

The header also has **Quick text…** (paste Russian, Ctrl+Enter), **Glossary…** and **About**.
Batch translation without the window: `RuEnTranslator.exe --translate a.pdf b.docx --out C:\folder [--pdf-docx]`
(Microsoft Store version: `ruentranslator --translate ...`).

## What it handles

- **Documents:** `.docx` (formatting, tables, headers/footers, footnotes kept), `.pdf` (text replaced in place, page layout kept — or exported to Word), `.txt` / `.md` (UTF-8, Windows-1251, KOI8-R, CP866).
- **Scans (OCR):** scanned PDFs and images (`.png`, `.jpg`, `.tif` incl. multi-page, `.bmp`) are read with built-in offline OCR. Tilted scans are straightened automatically. Output is a PDF with the English painted over the scan, or a Word document. ~3–5 s per page.
- **Glossary:** *Glossary…* edits your term list (stored in `%APPDATA%\RuEnTranslator\glossary.txt`). One `русский термин = English term` per line. Word endings are matched loosely, so `первый контур` also catches `первом контуре`.
- Originals are never modified.
- **Legal and government terms** are handled built-in (`rutrans/legal.py`): kray, oblast,
  autonomous okrug, Council of the Federation, Prosecutor General — only in unambiguous
  contexts, so ordinary words like "область знаний" are translated normally.
- **Benchmark:** the 76-page scanned Russian Constitution, scored against its official English
  text, gives BLEU 44.1 / chrF 71.1 (version 1.3: 39.7 / 68.0).
- Speed (4-core laptop): ~1–1.5 s per typed page, ~4–7 s per dense scanned page (two pages are
  read at once). No page limit.
- The time-left estimate learns this PC's speed (`%APPDATA%\RuEnTranslator\speed.json`), so it
  gets more accurate after the first few documents.

## Engine

[Opus-MT ru-en](https://github.com/Helsinki-NLP/OPUS-MT-train) (Marian transformer, CC-BY 4.0, University of Helsinki) quantised to int8 and run with [CTranslate2](https://github.com/OpenNMT/CTranslate2) on the CPU. ~80 MB model, ~2 s start-up, ~25–30 sentences/s on a laptop CPU.

OCR: [RapidOCR](https://github.com/RapidAI/RapidOCR) with PaddleOCR PP-OCRv5 models (Apache-2.0) — the mobile text detector and the East-Slavic (Russian/Ukrainian/Belarusian) recogniser, ~13 MB, run with ONNX Runtime.

## Limits

- OCR quality depends on the scan: clean 200–300 dpi scans work very well; blurry phone photos, handwriting and stamps less so. Pages are OCR'd only when they have no text layer.
- On scans, English is painted over the original text with the sampled paper colour, so noisy/coloured paper shows flat patches. Bold/italic are not detected.
- PDF layout mode is best-effort: English text is fitted into the original text boxes (shrunk if needed). Use *Word document* PDF output for clean reflowable text.
- Old `.doc` files: save as `.docx` in Word first.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# get and convert the model (once)
Invoke-WebRequest https://object.pouta.csc.fi/OPUS-MT-models/ru-en/opus-2020-02-26.zip -OutFile build_src\opus-ru-en.zip
Expand-Archive build_src\opus-ru-en.zip build_src\opus_ru_en
.\.venv\Scripts\python.exe tools\convert_model.py build_src\opus_ru_en models\opus-mt-ru-en
# get the OCR models (once) -> models\ocr
.\.venv\Scripts\python.exe tools\get_ocr_models.py
# run
.\.venv\Scripts\python.exe run.py
# tests (sample documents + off-screen GUI run)
.\.venv\Scripts\python.exe tools\make_samples.py samples
.\.venv\Scripts\python.exe tools\test_docs.py samples
.\.venv\Scripts\python.exe tools\test_gui.py samples
# build dist\RuEnTranslator\ and a portable zip
powershell -ExecutionPolicy Bypass -File build.ps1
# Microsoft Store package (identity values from Partner Center > Product identity)
powershell -ExecutionPolicy Bypass -File build_msix.ps1 -IdentityName "..." -Publisher "CN=..." -PublisherDisplayName "Aexonlab"
```

Store listing text and screenshots: `packaging/STORE_LISTING.md`, `packaging/store-screenshots/`
(regenerate with `packaging/make_screenshots.py <scanned Russian PDF>`).

## Licence

RuEn Translator is free software under the GNU Affero General Public License v3 or later
(`LICENSE`). It bundles the OPUS-MT ru-en model (University of Helsinki, CC BY 4.0), PaddleOCR
models (Apache 2.0) and the libraries listed in `THIRD_PARTY_NOTICES.md`. Privacy: `PRIVACY.md`
(no data collection, no network use).
