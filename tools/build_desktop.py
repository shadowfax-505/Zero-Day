"""Build a stand-alone desktop app with PyInstaller (no Python needed to play).

    pip install pyinstaller
    python tools/build_desktop.py        # -> dist/Zero Day/ (Windows, Linux) or dist/Zero Day.app (macOS)

.github/workflows/desktop.yml runs this on Windows, macOS and Linux for every v* tag.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEP = ";" if os.name == "nt" else ":"


def main():
    data = [("assets", "assets")] + [(os.path.join("tuning", f), "tuning") for f in
                                     ("best_weights.json", "red_weights.json", "blue_policy.json", "red_value.json")]
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "Zero Day",
            "--hidden-import", "websockets.sync.client"]
    for src, dst in data:
        args += ["--add-data", f"{os.path.join(ROOT, src)}{SEP}{dst}"]
    args.append(os.path.join(ROOT, "main.py"))
    print(" ".join(args))
    sys.exit(subprocess.call(args, cwd=ROOT))


if __name__ == "__main__":
    main()
