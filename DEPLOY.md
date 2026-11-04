# Putting Zero Day online

**Where it lives now**

- Browser game: <https://shadowfax-505.github.io/Zero-Day/> (GitHub Pages, rebuilt on every push to `main`)
- Relay server: <https://zero-day-relay.onrender.com> (Render free plan, deploys from `main`)
- Desktop apps: built when a `v*` tag is pushed (see section 3). No release has been tagged yet.

The rest of this file is how we set those up, in case you want to run your own copy.

There are three pieces, and each one is free:

| Piece | What it is | Where it runs |
|---|---|---|
| **Relay server** | `server/relay.py`, a tiny WebSocket server that pairs two players by a four-letter code and passes their moves between them | Render (or Fly.io) |
| **Web version** | The same Pygame game compiled for the browser with pygbag | GitHub Pages and/or itch.io |
| **Desktop apps** | Double-clickable builds for Windows, macOS and Linux (PyInstaller) | GitHub Releases |

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

`.github/workflows/desktop.yml` builds Windows, macOS and Linux apps with PyInstaller.

* **Make a release:** `git tag v1.0 && git push origin v1.0`. The apps are attached to a GitHub
  Release called v1.0 a few minutes later.
* **Just try a build:** **Actions → Desktop builds → Run workflow**, then download the zips from
  the run page.

The apps are not code-signed. On Windows click **More info → Run anyway**; on macOS right-click
the app, choose **Open**, then **Open** again.

To build one on your own computer: `pip install pyinstaller` then `python tools/build_desktop.py`
(the result is in `dist/`).

## Playing online

* **Host:** PLAY ONLINE → CONNECT: THROUGH THE SERVER → HOST A GAME. A four-letter code appears.
* **Join:** PLAY ONLINE → CONNECT: THROUGH THE SERVER → type the code in JOIN BY CODE (or click
  the game in the list on the right).
* From the command line: `python main.py --online --relay wss://zero-day-relay.onrender.com`.
