# /// script
# dependencies = ["numpy"]
# ///
"""Zero Day: Red AI (intruder) vs Blue AI (defender) on a network under fog of war.

    python main.py                       # main menu
    python main.py --mode ai --seed 42   # straight into an AI vs AI match
    python main.py --mode red            # you play Red against the Blue AI
    python main.py --mode blue           # you play Blue against the Red AI
    python main.py --host --side red     # host an online game (other player joins)
    python main.py --join 192.168.1.20   # join a game hosted on that computer
    python main.py --theme dark          # the original neon look (also in Settings, or press T)
    python main.py --online              # open the online lobby (direct, or through the relay server)
    python main.py --relay wss://...     # use this relay server for online play

The same file starts the browser build (pygbag, see DEPLOY.md).
"""

import argparse
import asyncio
import os
import sys

WEB = sys.platform == "emscripten"


def web_log(text):
    """Browser build: also write to the page's JavaScript console (print() only reaches pygbag's terminal)."""
    if WEB:
        try:
            import platform as _pf
            _pf.window.console.log(str(text))
        except Exception:  # noqa: BLE001
            pass


async def main():
    ap = argparse.ArgumentParser(description="Zero Day - Red AI vs Blue AI")
    ap.add_argument("--mode", choices=["ai", "red", "blue"], help="skip the menu and start this mode")
    ap.add_argument("--seed", type=int, help="map seed (same seed, same map)")
    ap.add_argument("--speed", type=float, choices=[0.5, 1, 2, 4], help="default: from Settings")
    ap.add_argument("--view", choices=["red", "full", "blue"], help="default: from Settings")
    ap.add_argument("--theme", choices=["paper", "dark"], help="default: from Settings")
    ap.add_argument("--fullscreen", action="store_true", help="default: from Settings")
    ap.add_argument("--host", action="store_true", help="host an online game and wait for someone to join")
    ap.add_argument("--join", metavar="IP", help="join the online game hosted at this address")
    ap.add_argument("--port", type=int, default=5150, help="port for online play (default 5150)")
    ap.add_argument("--side", choices=["red", "blue"], help="side to play when hosting")
    ap.add_argument("--ai", action="store_true", help="online: let your AI play your side")
    ap.add_argument("--name", help="your name in online games")
    ap.add_argument("--online", action="store_true", help="open the online lobby")
    ap.add_argument("--relay", metavar="URL", help="relay server for online play (default: the one in net/relay.py)")
    ap.add_argument("--record", metavar="DIR", help="save every frame as a PNG (30 fps) for the gameplay video")
    args = ap.parse_args([] if WEB else None)
    if args.relay:
        os.environ["ZERO_DAY_RELAY"] = args.relay

    from ui.app import App
    speed = None if args.speed is None else (int(args.speed) if args.speed >= 1 else args.speed)
    online = None
    if args.online and not (args.host or args.join):
        online = {}
    if args.host or args.join:
        online = {"host": args.host, "join": args.join, "port": args.port, "side": args.side, "ai": args.ai,
                  "name": args.name}
    app = App(args.mode, args.seed, speed, args.view, windowed=False if args.fullscreen else None,
              record=args.record, theme=args.theme, online=online)
    await app.run_async()


async def run():
    try:
        await main()
    except Exception:
        import traceback
        web_log("Zero Day crashed:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    asyncio.run(run())
