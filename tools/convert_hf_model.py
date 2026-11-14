"""Download a Hugging Face Marian (OPUS-MT) model and convert it to an int8 CTranslate2 model.

Usage: python tools/convert_hf_model.py Helsinki-NLP/opus-mt-tc-big-zle-en models/opus-mt-tc-big-zle-en
Needs (development only, not shipped): torch (CPU), transformers, huggingface_hub.
"""
import shutil
import sys
from pathlib import Path

from ctranslate2.converters import TransformersConverter
from huggingface_hub import snapshot_download

repo, dst = sys.argv[1], Path(sys.argv[2])
src = Path(snapshot_download(repo, allow_patterns=["*.json", "*.spm", "*.bin", "*.safetensors",
                                                    "*.txt", "*.md", "LICENSE*"]))
TransformersConverter(str(src)).convert(str(dst), quantization="int8", force=True)
for name in ("source.spm", "target.spm", "README.md", "LICENSE"):
    if (src / name).exists():
        shutil.copy(src / name, dst / name)
(dst / "SOURCE.txt").write_text(f"Converted from https://huggingface.co/{repo}\n", encoding="utf-8")
print("Model written to", dst)
for f in sorted(dst.iterdir()):
    print(f"  {f.name:24s} {f.stat().st_size / 1e6:8.1f} MB")
