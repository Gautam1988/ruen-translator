import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False) and os.name == "nt":
    # PyInstaller de-duplicates vendored DLLs (numpy.libs, sentencepiece.libs, ...) into one
    # of the folders, but each package only searches its own: make all of them searchable.
    for d in Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).glob("*.libs"):
        os.add_dll_directory(str(d))

from rutrans.app import main  # noqa: E402

if __name__ == "__main__":
    main()
