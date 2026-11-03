"""Player settings, saved to ~/.zero_day/settings.json between runs.

SPEC lists every option in the order the settings screen shows them. To add
an option, add a row here (and read it where it matters): the screen, saving
and loading all pick it up automatically."""

import json
import os

PATH = os.path.join(os.path.expanduser("~"), ".zero_day", "settings.json")

# key, label, choices (value, shown text), default, help line
SPEC = [
    ("section", "Display"),
    ("theme", "Theme", [("paper", "Paper"), ("dark", "Dark")], "paper",
     "Paper is the printed-map look. Dark is the original neon look."),
    ("fullscreen", "Fullscreen", [(False, "Off"), (True, "On")], False, "Also toggled any time with F11."),
    ("labels", "Node labels", [(True, "On"), (False, "Off")], True, "Names under each node (SRV-01, WS-04...)."),
    ("tooltips", "Hover info", [(True, "On"), (False, "Off")], True, "Point at a node to see what is known about it."),
    ("effects", "Animations", [(True, "Full"), (False, "Reduced")], True,
     "Reduced turns off ripples, flashes and floating text."),
    ("show_fps", "FPS counter", [(False, "Off"), (True, "On")], False, "Frames per second in the corner."),
    ("section", "Match"),
    ("speed", "Default speed", [(0.5, "0.5x"), (1, "1x"), (2, "2x"), (4, "4x")], 1,
     "How fast AI vs AI rounds play. Change in a match with + and -."),
    ("view", "Default view", [("full", "Full"), ("red", "Red"), ("blue", "Blue")], "full",
     "Which side's knowledge AI vs AI starts on. Switch with V or 1 2 3."),
    ("auto_next", "Auto next match", [(False, "Off"), (True, "On")], False,
     "AI vs AI starts a new map by itself a few seconds after a win (demo mode)."),
    ("confirm_turn", "Blue: confirm turn", [(True, "Enter"), (False, "Auto")], True,
     "Playing Blue: Auto ends your turn as soon as your action points run out."),
    ("section", "Sound"),
    ("sound", "Sound effects", [(True, "On"), (False, "Off")], True, "Short tones for captures, alerts and wins."),
    ("volume", "Volume", [(v, f"{int(v * 100)}%") for v in (0.2, 0.4, 0.6, 0.8, 1.0)], 0.6, ""),
]

OPTIONS = [row for row in SPEC if row[0] != "section"]


class Settings:
    def __init__(self, path=PATH):
        self.path = path
        self.values = {key: default for key, _, _, default, _ in OPTIONS}
        self.load()

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value

    def choices(self, key):
        return next(c for k, _, c, _, _ in OPTIONS if k == key)

    def step(self, key, d=1):
        """Move an option to its next (d=1) or previous (d=-1) choice."""
        vals = [v for v, _ in self.choices(key)]
        i = vals.index(self.values[key]) if self.values[key] in vals else 0
        self.values[key] = vals[(i + d) % len(vals)]
        return self.values[key]

    def shown(self, key):
        return dict(self.choices(key)).get(self.values[key], str(self.values[key]))

    def load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for key, _, choices, _, _ in OPTIONS:
            if key in data and data[key] in [v for v, _ in choices]:
                self.values[key] = data[key]

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self.values, f, indent=2)
        except OSError:
            pass
