# Putting Zero Day online

**Where it lives now**

- Browser game: <https://shadowfax-505.github.io/Zero-Day/> (GitHub Pages, rebuilt on every push to `main`)
- Relay server: <https://zero-day-relay.onrender.com> (Render free plan, deploys from `main`)
- Desktop apps: installers for Windows, macOS and Linux, built when a `v*` tag is pushed (see section 3).

The rest of this file is how we set those up, in case you want to run your own copy.

There are three pieces, and each one is free:

| Piece | What it is | Where it runs |
|---|---|---|
| **Relay server** | `server/relay.py`, a tiny WebSocket server that pairs two players by a four-letter code and passes their moves between them | Render (or Fly.io) |
| **Web version** | The same Pygame game compiled for the browser with pygbag | GitHub Pages and/or itch.io |
| **Desktop apps** | Windows installer, macOS .dmg (Apple Silicon and Intel), Linux AppImage (PyInstaller) | GitHub Releases |

The relay never runs the game. Both players' copies run the same match in lockstep, exactly as in
direct LAN play, and only moves and chat go through the server. Desktop copies can still play
directly on the same network (or by IP) without the relay. Browser players always use the relay,
and a browser player and a desktop player can play each other through it.

## 1. Deploy the relay server (Render, about 5 minutes)

1. Sign in at <https://render.com> with your GitHub account.
2. **New → Blueprint**, pick the `Zero-Day` repository, and confirm. Render reads `render.yaml`
   and creates a free web service called `zero-day-relay`.
3. When it shows **Live**, open its URL (for example `https://zero-day-relay.onrender.com`).
   You should see `Zero Day relay OK. 0 room(s) open.`
4. If Render gave the service a different address (the name was taken, so it added a suffix), put
   that address in `DEFAULT_RELAY` in `net/relay.py`, with `wss://` instead of `https://`, and
   commit. Players can also type it in the lobby's **SERVER** row.

A free Render service goes to sleep after 15 minutes without visitors. The first player to connect
after that waits up to a minute while it wakes up; the lobby says so on screen. For the showcase,
open the relay URL in a browser a minute before you start.

**Fly.io instead (always on, needs a card on file):** install `flyctl`, then from the `server/`
folder run `fly launch --copy-config --no-deploy` (pick a unique app name), then `fly deploy`.
The relay address is `wss://<app-name>.fly.dev`.

## 2. Publish the web version

### GitHub Pages (automatic)

1. In the repository on GitHub: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. Every push to `main` runs `.github/workflows/web.yml`, which builds the game with pygbag,
   plays it in a headless browser as a smoke test, and publishes it.
3. The game is then at `https://shadowfax-505.github.io/Zero-Day/`.

To point a page at a different relay without rebuilding, add it to the address:
`https://shadowfax-505.github.io/Zero-Day/?relay=wss://my-relay.onrender.com`.

### itch.io (optional)

1. Open the latest **Web build** run in the repository's **Actions** tab and download the
   `zero-day-web-itch-io` artifact. Unzip it once; inside is `web.zip`.
2. On itch.io: **Create new project → Kind of project: HTML**, upload `web.zip`, tick
   **This file will be played in the browser**, and set the viewport to 1280 × 720 with the
   fullscreen button on.

### Building it yourself

```
pip install pygbag
python tools/build_web.py --serve      # then open http://localhost:8000
```

The browser version has everything the desktop one has except LAN discovery and direct IP play.
Settings in the browser last until the tab is closed.

## 3. Desktop apps on GitHub Releases

`.github/workflows/desktop.yml` builds the apps with PyInstaller and packages them so nobody needs
Python to play:

| File | For |
| --- | --- |
| `ZeroDay-Windows-Setup.exe` | Windows installer (Start menu and desktop shortcut, per-user, no admin) |
| `ZeroDay-Windows-Portable.zip` | Windows without installing |
| `ZeroDay-macOS-AppleSilicon.dmg` | Macs with an Apple chip |
| `ZeroDay-macOS-Intel.dmg` | Intel Macs |
| `ZeroDay-Linux-x86_64.AppImage` | Linux, one file (built on Ubuntu 22.04 so it runs on older distributions too) |
| `ZeroDay-Linux-x86_64.tar.gz` | Linux, plain folder |

Before a build is uploaded, the workflow starts it with no window and checks that it plays a few
seconds of an AI vs AI match (`tools/smoke_desktop.py`). The Windows installer and the macOS disk
image are tested the same way after installing from them.

* **Make a release:** `git tag v1.1 && git push origin v1.1`. All six files are attached to a GitHub
  Release called v1.1 about 10 minutes later, with the download table from
  `tools/installer/release-notes.md` as its description.
* **Add the files to a release that already exists:** **Actions → Desktop builds → Run workflow** and
  type its tag (for example `v1.0`) in the box.
* **Just try a build:** **Actions → Desktop builds → Run workflow** with the box left empty, then
  download the files from the run page.

The file names stay the same in every version, so the links in the README
(`releases/latest/download/<file>`) always point at the newest release.

The apps are not code-signed. On Windows click **More info → Run anyway**. On macOS open
**System Settings → Privacy & Security** and click **Open Anyway** (on macOS 14 or older, right-click
the app and choose **Open**). Removing these warnings needs a paid Apple Developer account and a
Windows code-signing certificate.

To build on your own computer:

```bash
pip install pyinstaller pillow
python tools/build_desktop.py        # the app, in dist/
python tools/package_desktop.py      # the installer, .dmg or AppImage, in release/
```

The Windows installer needs [Inno Setup](https://jrsoftware.org/isinfo.php) installed.

## Playing online

* **Host:** PLAY ONLINE → CONNECT: THROUGH THE SERVER → HOST A GAME. A four-letter code appears.
* **Join:** PLAY ONLINE → CONNECT: THROUGH THE SERVER → type the code in JOIN BY CODE (or click
  the game in the list on the right).
* From the command line: `python main.py --online --relay wss://zero-day-relay.onrender.com`.
