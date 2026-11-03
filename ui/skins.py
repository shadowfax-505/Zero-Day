"""The two looks the game can wear. 'paper' (default) is the printed
operations map; 'dark' is the original neon look. Each skin bundles its
theme, effects, board renderer, panels and screens behind the same names."""

from types import SimpleNamespace

THEMES = ["paper", "dark"]
THEME_NAMES = {"paper": "Paper (default)", "dark": "Dark"}


def load(name):
    if name == "dark":
        from ui.neon import board, fx, panels, screens, theme
    else:
        from ui import board, fx, panels, screens, theme
    return SimpleNamespace(name=name if name in THEMES else "paper", T=theme, fx=fx, board=board, panels=panels,
                           screens=screens)
