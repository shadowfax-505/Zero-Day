"""Zero Day: Red AI (intruder) vs Blue AI (defender) on a network under fog of war.

    python main.py                       # main menu
    python main.py --mode ai --seed 42   # straight into an AI vs AI match
    python main.py --mode red            # you play Red against the Blue AI
    python main.py --mode blue           # you play Blue against the Red AI
    python main.py --theme dark          # the original neon look (also in Settings, or press T)
"""

import argparse


def main():
    ap = argparse.ArgumentParser(description="Zero Day - Red AI vs Blue AI")
    ap.add_argument("--mode", choices=["ai", "red", "blue"], help="skip the menu and start this mode")
    ap.add_argument("--seed", type=int, help="map seed (same seed, same map)")
    ap.add_argument("--speed", type=float, choices=[0.5, 1, 2, 4], help="default: from Settings")
    ap.add_argument("--view", choices=["red", "full", "blue"], help="default: from Settings")
    ap.add_argument("--theme", choices=["paper", "dark"], help="default: from Settings")
    ap.add_argument("--fullscreen", action="store_true", help="default: from Settings")
    ap.add_argument("--record", metavar="DIR", help="save every frame as a PNG (30 fps) for the gameplay video")
    args = ap.parse_args()

    from ui.app import App
    speed = None if args.speed is None else (int(args.speed) if args.speed >= 1 else args.speed)
    App(args.mode, args.seed, speed, args.view, windowed=False if args.fullscreen else None, record=args.record,
        theme=args.theme).run()


if __name__ == "__main__":
    main()
