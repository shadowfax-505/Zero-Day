"""Check that a packaged desktop build really starts and plays a match.

    python tools/smoke_desktop.py "dist/Zero Day/Zero Day"
    python tools/smoke_desktop.py release/ZeroDay-Linux-x86_64.AppImage

Runs an AI vs AI match with no window (SDL dummy drivers) and asks the game to save frames.
The build passes once frames start to appear, which means the bundled Python, pygame, numpy,
fonts and AI weights all loaded and the match loop is running.
"""

import os
import subprocess
import sys
import tempfile
import time

NEED, TIMEOUT = 30, 120


def main():
    exe = os.path.abspath(sys.argv[1])
    frames = tempfile.mkdtemp(prefix="zero-day-smoke-")
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", APPIMAGE_EXTRACT_AND_RUN="1")
    proc = subprocess.Popen([exe, "--mode", "ai", "--seed", "1", "--record", frames], env=env)
    start = time.time()
    try:
        while time.time() - start < TIMEOUT:
            n = len([f for f in os.listdir(frames) if f.endswith(".png")])
            if n >= NEED:
                print(f"ok: {n} frames after {time.time() - start:.0f}s")
                return
            if proc.poll() is not None:
                sys.exit(f"the game exited with code {proc.returncode} after {n} frames")
            time.sleep(1)
        sys.exit(f"only {n} frames after {TIMEOUT}s")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    main()
