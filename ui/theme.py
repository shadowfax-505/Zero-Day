"""Colours, fonts and layout constants. Matches the proposal deck: dark navy,
Red in glowing red, Blue's defences and belief in blue, the database in gold."""

import os

import pygame

W, H = 1600, 900
TOP_H = 64
SIDE_W = 340
BOTTOM_H = 150
BOARD = pygame.Rect(SIDE_W + 16, TOP_H + 12, W - 2 * SIDE_W - 32, H - TOP_H - BOTTOM_H - 24)

BG = (5, 9, 22)
BG2 = (9, 16, 36)
GRID = (14, 25, 50)
PANEL = (10, 17, 36)
PANEL_EDGE = (28, 44, 80)
TEXT = (226, 233, 245)
MUTED = (122, 140, 175)
DIM = (70, 86, 120)
EDGE = (40, 66, 110)
EDGE_LIT = (80, 120, 180)
NODE = (12, 22, 46)
NODE_RING = (96, 130, 190)
RED = (255, 59, 92)
RED_SOFT = (255, 120, 140)
BLUE = (64, 156, 255)
BLUE_SOFT = (130, 190, 255)
CYAN = (60, 230, 230)
GOLD = (255, 194, 75)
AMBER = (255, 170, 40)
GREEN = (80, 230, 160)
WHITE = (255, 255, 255)
ZONE_TINT = [(30, 50, 95), (24, 40, 80), (40, 34, 70)]

ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
_fonts = {}


def font(size, weight="regular", mono=False):
    key = (size, weight, mono)
    if key not in _fonts:
        if mono:
            name = "DejaVuSansMono-Bold.ttf" if weight == "bold" else "DejaVuSansMono.ttf"
        else:
            name = {"regular": "Inter-Regular.otf", "medium": "Inter-Medium.otf", "semibold": "Inter-SemiBold.otf",
                    "bold": "Inter-Bold.otf", "black": "InterDisplay-Black.otf"}[weight]
        path = os.path.join(ASSETS, name)
        try:
            _fonts[key] = pygame.font.Font(path, size)
        except (FileNotFoundError, OSError):
            _fonts[key] = pygame.font.SysFont("dejavusans", size, bold=weight in ("bold", "black"))
    return _fonts[key]


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


def scale(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)
