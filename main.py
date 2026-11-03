"""Zero Day: Red AI (intruder) vs Blue AI (defender) on a network under fog of war.

    python main.py                       # main menu
    python main.py --mode ai --seed 42   # straight into an AI vs AI match
    python main.py --mode red            # you play Red against the Blue AI
    python main.py --mode blue           # you play Blue against the Red AI
    python main.py --host --side red     # host an online game (other player joins)
    python main.py --join 192.168.1.20   # join a game hosted on that computer
"""

import argparse


def main():
    ap = argparse.ArgumentParser(description="Zero Day - Red AI vs Blue AI")
    ap.add_argument("--mode", choices=["ai", "red", "blue"], help="skip the menu and start this mode")
    ap.add_argument("--seed", type=int, help="map seed (same seed, same map)")
    ap.add_argument("--speed", type=float, default=1, choices=[0.5, 1, 2, 4])
    ap.add_argument("--view", choices=["red", "full", "blue"], default="full")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--host", action="store_true", help="host an online game and wait for someone to join")
    ap.add_argument("--join", metavar="IP", help="join the online game hosted at this address")
    ap.add_argument("--port", type=int, default=5150, help="port for online play (default 5150)")
    ap.add_argument("--side", choices=["red", "blue"], help="side to play when hosting")
    ap.add_argument("--ai", action="store_true", help="online: let your AI play your side")
    ap.add_argument("--name", help="your name in online games")
    ap.add_argument("--record", metavar="DIR", help="save every frame as a PNG (30 fps) for the gameplay video")
    args = ap.parse_args()

    from ui.app import App
    speed = int(args.speed) if args.speed >= 1 else args.speed
    online = None
    if args.host or args.join:
        online = {"host": args.host, "join": args.join, "port": args.port, "side": args.side, "ai": args.ai,
                  "name": args.name}
    App(args.mode, args.seed, speed, args.view, windowed=not args.fullscreen, record=args.record,
        online=online).run()


if __name__ == "__main__":
    main()
