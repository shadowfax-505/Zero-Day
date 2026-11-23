"""Build a stand-alone desktop app with PyInstaller (no Python needed to play).

    pip install pyinstaller pillow
    python tools/build_desktop.py        # -> dist/Zero Day/ (Windows, Linux) or dist/Zero Day.app (macOS)
    python tools/package_desktop.py      # -> release/ (installer, .dmg or AppImage for this computer)

.github/workflows/desktop.yml runs both on Windows, macOS (Apple Silicon and Intel) and Linux.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP = ";" if os.name == "nt" else ":"
ICON = os.path.join(ROOT, "assets", "icon")


def main():
    data = [("assets", "assets")] + [(os.path.join("tuning", f), "tuning") for f in
                                     ("best_weights.json", "red_weights.json", "blue_policy.json", "red_value.json")]
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "Zero Day",
            "--hidden-import", "websockets.sync.client", "--hidden-import", "pygame._sdl2.video"]
    if sys.platform == "win32":
        args += ["--icon", os.path.join(ICON, "icon.ico")]
    elif sys.platform == "darwin":
        args += ["--icon", os.path.join(ICON, "icon.icns"),
                 "--osx-bundle-identifier", "io.github.shadowfax505.zeroday"]
    for src, dst in data:
        args += ["--add-data", f"{os.path.join(ROOT, src)}{SEP}{dst}"]
    args.append(os.path.join(ROOT, "main.py"))
    print(" ".join(args))
    sys.exit(subprocess.call(args, cwd=ROOT))


if __name__ == "__main__":
    main()
