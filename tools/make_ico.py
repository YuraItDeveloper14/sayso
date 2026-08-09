"""Wrap the 128px logo PNG in a Windows .ico container.

PyInstaller and Explorer shortcuts want .ico, and an .ico since Vista is just a
small header around PNG data - no image library needed to build one.

    python tools/make_ico.py
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "extension" / "icons" / "icon128.png"
TARGET = ROOT / "static" / "sayso.ico"


def main():
    if not SOURCE.exists():
        print(f"missing {SOURCE}")
        return 1

    png = SOURCE.read_bytes()
    if not png.startswith(b"\x89PNG"):
        print("source is not a PNG")
        return 1

    header = struct.pack("<HHH", 0, 1, 1)          # reserved, type=icon, count
    entry = struct.pack(
        "<BBBBHHII",
        128, 128,       # width, height (0 would mean 256)
        0, 0,           # palette size, reserved
        1, 32,          # colour planes, bits per pixel
        len(png),       # bytes of image data
        6 + 16,         # offset: past this header and one entry
    )
    TARGET.write_bytes(header + entry + png)
    print(f"wrote {TARGET.name}, {TARGET.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
