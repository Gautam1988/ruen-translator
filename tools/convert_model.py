"""Convert the original Opus-MT ru-en Marian model to an int8 CTranslate2 model.

Usage: python tools/convert_model.py build_src/opus_ru_en models/opus-mt-ru-en
"""
import shutil
import sys
from pathlib import Path

from ctranslate2.converters import OpusMTConverter

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
OpusMTConverter(str(src)).convert(str(dst), quantization="int8", force=True)
for name in ("source.spm", "target.spm", "LICENSE", "README.md"):
    shutil.copy(src / name, dst / name)
print("Model written to", dst)
for f in sorted(dst.iterdir()):
    print(f"  {f.name:20s} {f.stat().st_size / 1e6:8.1f} MB")
