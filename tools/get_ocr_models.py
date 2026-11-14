"""Download the OCR models (PP-OCRv5 mobile detector + East-Slavic recogniser) into models/ocr.

RapidOCR fetches and SHA-256-checks them from its official model store.
"""
from pathlib import Path

from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR

dst = Path(__file__).resolve().parent.parent / "models" / "ocr"
dst.mkdir(parents=True, exist_ok=True)
RapidOCR(params={
    "Global.use_cls": False, "Global.model_root_dir": str(dst),
    "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
    "Det.lang_type": LangDet.MULTI,
    "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
    "Rec.lang_type": LangRec.ESLAV,
})
for f in sorted(dst.iterdir()):
    print(f"{f.name:36s} {f.stat().st_size / 1e6:6.1f} MB")
