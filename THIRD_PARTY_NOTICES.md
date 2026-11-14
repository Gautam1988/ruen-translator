# Third-party notices

RuEn Translator is licensed under the GNU Affero General Public License v3.0 or later (see `LICENSE`).
The Windows app bundles the components below. Each one remains under its own licence.

## Models

| Model | Licence | Source |
|---|---|---|
| OPUS-MT ru-en (opus-2020-02-26), Language Technology Research Group, University of Helsinki. Converted to CTranslate2 int8 format; not otherwise modified. | Creative Commons Attribution 4.0 (CC BY 4.0) | https://github.com/Helsinki-NLP/OPUS-MT-train — https://object.pouta.csc.fi/OPUS-MT-models/ru-en/opus-2020-02-26.zip |
| PaddleOCR PP-OCRv5 mobile text detector and East-Slavic (eslav) text recogniser, PaddlePaddle authors, in ONNX format from RapidOCR | Apache License 2.0 | https://github.com/PaddlePaddle/PaddleOCR — https://github.com/RapidAI/RapidOCR |

Translations are produced by the OPUS-MT model: Tiedemann, J. and Thottingal, S. (2020),
"OPUS-MT — Building open translation services for the World", EAMT 2020.

## Libraries

| Component | Version | Licence | Source |
|---|---|---|---|
| PyMuPDF (includes the MuPDF library) | 2.1 (MuPDF 1.28.6) | GNU AGPL v3.0, or a commercial licence from Artifex | https://github.com/pymupdf/PyMuPDF |
| Qt for Python (PySide6, Shiboken6) and Qt 6 | 6.12.0 | GNU LGPL v3.0 | https://code.qt.io/cgit/pyside/pyside-setup.git/ , https://code.qt.io/ |
| CTranslate2 | 4.8.5 | MIT | https://github.com/OpenNMT/CTranslate2 |
| SentencePiece | 0.2.3 | Apache License 2.0 | https://github.com/google/sentencepiece |
| ONNX Runtime | 1.31.1 | MIT | https://github.com/microsoft/onnxruntime |
| RapidOCR | 3.10.0 | Apache License 2.0 | https://github.com/RapidAI/RapidOCR |
| OpenCV (opencv-python-headless) | 5.0.0 | Apache License 2.0 | https://github.com/opencv/opencv-python |
| NumPy | 2.5.4 | BSD-3-Clause (and bundled OpenBLAS: BSD-3-Clause) | https://github.com/numpy/numpy |
| python-docx | 1.2.0 | MIT | https://github.com/python-openxml/python-docx |
| lxml (includes libxml2, libxslt) | 6.1.3 | BSD-3-Clause (libxml2/libxslt: MIT) | https://github.com/lxml/lxml |
| Pillow | 13.0.0 | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| Shapely (includes GEOS) | 2.2.0 | BSD-3-Clause (GEOS: LGPL v2.1) | https://github.com/shapely/shapely |
| pyclipper (includes Clipper) | 1.4.0 | MIT (Clipper: Boost Software License) | https://github.com/fonttools/pyclipper |
| OmegaConf (with ANTLR 4 runtime) | 2.4.0 | BSD-3-Clause | https://github.com/omry/omegaconf |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| requests, certifi, charset-normalizer, idna, urllib3 | various | Apache 2.0 / MPL 2.0 / MIT | https://pypi.org (bundled as RapidOCR dependencies; not used for network access) |
| colorlog, tqdm, six | various | MIT / MPL 2.0 | https://pypi.org |
| Python | 3.12.10 | Python Software Foundation License | https://www.python.org/downloads/source/ |
| PyInstaller bootloader | 6.22.3 | GPL v2 or later, with the bootloader exception that allows bundling apps under any licence | https://github.com/pyinstaller/pyinstaller |

MuPDF also includes third-party libraries such as FreeType, HarfBuzz, libjpeg, OpenJPEG, jbig2dec,
lcms2, zlib and Gumbo. Their notices ship with the PyMuPDF and MuPDF source distributions linked
above. Qt is used as dynamically linked libraries; you may replace them with your own build of
the same Qt version.

## Corresponding source

The source code of RuEn Translator itself, including the build scripts, is at
https://github.com/Gautam1988/ruen-translator. Every release is tagged.

The exact versions of the libraries bundled in a release are listed above and in
`requirements.txt`. Their source code is at the project links above. The models are downloaded and
converted by `tools/convert_model.py` and `tools/get_ocr_models.py`; you can rebuild the app with
`build.ps1`.
