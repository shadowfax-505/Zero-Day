"""Colours, fonts and layout constants.

Art direction: a printed operations map. Warm paper, black ink for the network,
two spot inks for the sides (vermilion for Red, Prussian blue for Blue), ochre
for the database and orange only for alerts. No glows, no gradients: shapes,
hatching and type do the work."""

import os

import pygame

W, H = 1600, 900
TOP_H = 64
SIDE_W = 340
BOTTOM_H = 150
BOARD = pygame.Rect(SIDE_W + 16, TOP_H + 12, W - 2 * SIDE_W - 32, H - TOP_H - BOTTOM_H - 24)

# paper and ink
PAPER = (237, 232, 221)
PAPER_2 = (229, 223, 209)       # zone tint, panel wells
PAPER_3 = (218, 211, 195)       # fog, bar tracks
GRID = (226, 220, 206)
RULE = (190, 182, 164)          # hairlines
INK = (30, 31, 34)
INK_2 = (86, 84, 78)            # secondary text
INK_3 = (138, 132, 120)         # tertiary text, idle links
EDGE = (128, 122, 110)

# spot colours
RED = (196, 52, 34)
RED_DARK = (140, 34, 22)
RED_TINT = (236, 200, 188)
BLUE = (28, 72, 138)
BLUE_DARK = (18, 46, 92)
BLUE_TINT = (200, 212, 230)
OCHRE = (172, 118, 16)
OCHRE_TINT = (238, 220, 176)
ALERT = (214, 112, 18)
GREEN = (62, 116, 72)

# names the rest of the UI uses
BG = PAPER
TEXT = INK
MUTED = INK_2
DIM = INK_3
GOLD = OCHRE
AMBER = ALERT
RED_SOFT = RED
BLUE_SOFT = BLUE

ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
_fonts = {}

_SANS = {"regular": "IBMPlexSans-Regular.ttf", "medium": "IBMPlexSans-Medium.ttf",
         "semibold": "IBMPlexSans-SemiBold.ttf", "bold": "IBMPlexSans-Bold.ttf", "black": "IBMPlexSans-Bold.ttf"}
_MONO = {"regular": "IBMPlexMono-Regular.ttf", "medium": "IBMPlexMono-Medium.ttf",
         "semibold": "IBMPlexMono-SemiBold.ttf", "bold": "IBMPlexMono-SemiBold.ttf", "black": "IBMPlexMono-SemiBold.ttf"}
_DISPLAY = {"regular": "BarlowCondensed-Medium.ttf", "medium": "BarlowCondensed-Medium.ttf",
            "semibold": "BarlowCondensed-SemiBold.ttf", "bold": "BarlowCondensed-Bold.ttf",
            "black": "BarlowCondensed-Bold.ttf"}


def font(size, weight="regular", mono=False, display=False):
    """IBM Plex Sans for text, Plex Mono for numbers, Barlow Condensed for headings."""
    key = (size, weight, mono, display)
    if key not in _fonts:
        table = _DISPLAY if display else _MONO if mono else _SANS
        path = os.path.join(ASSETS, table[weight])
        try:
            _fonts[key] = pygame.font.Font(path, size)
        except (FileNotFoundError, OSError):
            _fonts[key] = pygame.font.SysFont("dejavusans", size, bold=weight in ("bold", "black"))
    return _fonts[key]


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


def fade(c, k):
    """Colour c faded k of the way towards the paper (k=1 is invisible)."""
    return mix(c, PAPER, max(0.0, min(1.0, k)))


def scale(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)

# shared token names (both themes define these, so screens and overlays can use either)
NAME = "paper"
CYAN = BLUE
PANEL = PAPER_2
PANEL_EDGE = RULE
STRONG = INK
