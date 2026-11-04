"""Build the browser version with pygbag.

    pip install pygbag
    python tools/build_web.py            # -> build/zero-day/build/web/  (index.html + zero-day.apk)
    python tools/build_web.py --serve    # build, then serve it on http://localhost:8000

Only the files the game needs are copied (not the experiments, GA or tests),
which keeps the download small. Upload build/zero-day/build/web.zip to itch.io,
or let .github/workflows/web.yml publish it to GitHub Pages.
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "build", "zero-day")          # pygbag names the app after this folder
KEEP_DIRS = ["engine", "agents", "net", "ui", "assets"]
KEEP_FILES = ["main.py", "tuning/best_weights.json", "tuning/red_weights.json", "tuning/blue_policy.json",
              "tuning/red_value.json", "tuning/__init__.py"]


def copy():
    if os.path.exists(APP):
        shutil.rmtree(APP)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "LICENSE-*.txt")
    for d in KEEP_DIRS:
        shutil.copytree(os.path.join(ROOT, d), os.path.join(APP, d), ignore=ignore)
    for f in KEEP_FILES:
        src = os.path.join(ROOT, f)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(os.path.join(APP, f)), exist_ok=True)
            shutil.copy2(src, os.path.join(APP, f))
    # font licences still ship with the game
    lic = os.path.join(APP, "assets", "licences")
    os.makedirs(lic, exist_ok=True)
    for f in os.listdir(os.path.join(ROOT, "assets", "fonts")):
        if f.startswith("LICENSE"):
            shutil.copy2(os.path.join(ROOT, "assets", "fonts", f), lic)


def main():
    copy()
    args = [sys.executable, "-m", "pygbag", "--build", "--archive", "--title", "Zero Day",
            APP]
    if "--serve" in sys.argv:
        args.remove("--build")
    print(" ".join(args))
    sys.exit(subprocess.call(args))


if __name__ == "__main__":
    main()
