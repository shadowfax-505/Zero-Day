"""Turn the PyInstaller build in dist/ into the files players download.

    python tools/build_desktop.py
    python tools/package_desktop.py      # -> release/

What it makes on each system:

    Windows  ZeroDay-Windows-Setup.exe         installer (Start menu and desktop shortcuts, no admin needed)
             ZeroDay-Windows-Portable.zip      unzip and run, nothing installed
    macOS    ZeroDay-macOS-AppleSilicon.dmg    or ZeroDay-macOS-Intel.dmg, drag the app to Applications
    Linux    ZeroDay-Linux-x86_64.AppImage     one file, make it executable and run it
             ZeroDay-Linux-x86_64.tar.gz       plain folder

The file names never change between versions, so the README can link to
releases/latest/download/<name> and always get the newest build.
"""

import glob
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(ROOT, "release")
APPIMAGETOOL = ("https://github.com/AppImage/appimagetool/releases/download/continuous/"
                "appimagetool-x86_64.AppImage")


def version():
    v = os.environ.get("ZERO_DAY_VERSION") or os.environ.get("GITHUB_REF_NAME", "")
    return v[1:] if v.startswith("v") and v[1:2].isdigit() else "dev"


def run(args, **kw):
    print("+", " ".join(args), flush=True)
    subprocess.check_call(args, **kw)


def zip_dir(src, dest):
    base = os.path.dirname(src)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, _, files in os.walk(src):
            for f in files:
                p = os.path.join(folder, f)
                z.write(p, os.path.relpath(p, base))


def windows():
    app = os.path.join(DIST, "Zero Day")
    zip_dir(app, os.path.join(OUT, "ZeroDay-Windows-Portable.zip"))
    iscc = shutil.which("iscc") or next(iter(glob.glob(r"C:\Program Files*\Inno Setup *\ISCC.exe")), None)
    if not iscc:
        sys.exit("Inno Setup not found (choco install innosetup), only the portable zip was made")
    run([iscc, f"/DAppVersion={version()}", f"/DSourceDir={app}", f"/DOutputDir={OUT}",
         os.path.join(ROOT, "tools", "installer", "zero-day.iss")])


def macos():
    arch = "AppleSilicon" if platform.machine() == "arm64" else "Intel"
    app = os.path.join(DIST, "Zero Day.app")
    # the disk image shows the app next to a shortcut to Applications, so installing is one drag
    stage = os.path.join(ROOT, "build", "dmg")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    run(["ditto", app, os.path.join(stage, "Zero Day.app")])
    os.symlink("/Applications", os.path.join(stage, "Applications"))
    dmg = os.path.join(OUT, f"ZeroDay-macOS-{arch}.dmg")
    run(["hdiutil", "create", "-volname", "Zero Day", "-srcfolder", stage, "-ov", "-format", "UDZO", dmg])


def linux():
    app = os.path.join(DIST, "Zero Day")
    with tarfile.open(os.path.join(OUT, "ZeroDay-Linux-x86_64.tar.gz"), "w:gz") as t:
        t.add(app, arcname="Zero Day")

    appdir = os.path.join(ROOT, "build", "ZeroDay.AppDir")
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(app, os.path.join(appdir, "usr", "lib", "zero-day"), symlinks=True)
    shutil.copy2(os.path.join(ROOT, "assets", "icon", "icon.png"), os.path.join(appdir, "zero-day.png"))
    with open(os.path.join(appdir, "zero-day.desktop"), "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Zero Day\n"
                "Comment=Red AI vs Blue AI on a network neither can fully see\n"
                "Exec=zero-day\nIcon=zero-day\nCategories=Game;StrategyGame;\nTerminal=false\n")
    apprun = os.path.join(appdir, "AppRun")
    with open(apprun, "w") as f:
        f.write('#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\n'
                'exec "$HERE/usr/lib/zero-day/Zero Day" "$@"\n')
    os.chmod(apprun, 0o755)

    tool = os.path.join(ROOT, "build", "appimagetool")
    if not os.path.exists(tool):
        urllib.request.urlretrieve(APPIMAGETOOL, tool)
        os.chmod(tool, os.stat(tool).st_mode | stat.S_IEXEC)
    env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
    run([tool, "--no-appstream", appdir, os.path.join(OUT, "ZeroDay-Linux-x86_64.AppImage")], env=env)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    {"win32": windows, "darwin": macos}.get(sys.platform, linux)()
    for f in sorted(os.listdir(OUT)):
        print(f"{f}  {os.path.getsize(os.path.join(OUT, f)) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
