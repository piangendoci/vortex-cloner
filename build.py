"""Cross-platform build helper used locally and by GitHub Actions."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

NAME = "VORTEX CLONER"
EXE_NAME = f"{NAME}.exe" if os.name == "nt" else NAME


def main() -> int:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", NAME,
        "--clean",
        "--noconfirm",
        "--hidden-import=colorama",
        "--distpath", "dist",
        "--workpath", "build",
        "--specpath", ".",
        "vortex_main.py",
    ]
    subprocess.check_call(command)

    built = os.path.join("dist", EXE_NAME)
    if os.name == "nt" and os.path.isfile(built):
        shutil.copyfile(built, EXE_NAME)
        print(f"built: {EXE_NAME}")
    else:
        print(f"built: {built}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
