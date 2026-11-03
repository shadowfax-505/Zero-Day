"""Small sound effects made from tones at start-up (no audio files needed).
If there is no audio device, every call quietly does nothing."""

import math

import numpy as np
import pygame

RATE = 22050


def _make(freqs, dur, kind="sine", decay=6.0, gain=0.35, rate=RATE, channels=2):
    """Concatenated notes: freqs is a list of (frequency, seconds)."""
    parts = []
    for f, d in freqs:
        n = int(rate * d)
        t = np.arange(n) / rate
        if kind == "square":
            w = np.sign(np.sin(2 * math.pi * f * t)) * 0.5
        elif kind == "noise":
            w = np.random.default_rng(1).uniform(-1, 1, n)
        else:
            w = np.sin(2 * math.pi * f * t)
        env = np.exp(-decay * t / max(d, 1e-3))
        attack = np.minimum(1.0, t / 0.005)
        parts.append(w * env * attack)
    wave = np.concatenate(parts) * gain
    data = (wave * 32767).astype(np.int16)
    return data if channels == 1 else np.column_stack([data] * channels)


class Sound:
    def __init__(self):
        self.ok = False
        self.volume = 0.6
        self.enabled = True
        self.sounds = {}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(RATE, -16, 2, 512)
            rate, _, ch = pygame.mixer.get_init()

            def _tone(*a, **k):
                return _make(*a, rate=rate, channels=ch, **k)

            spec = {
                "capture": _tone([(520, 0.06), (780, 0.10)], 0.16),
                "fail": _tone([(300, 0.08), (220, 0.12)], 0.2, "square", gain=0.18),
                "scout": _tone([(880, 0.05), (1100, 0.05)], 0.1, gain=0.2),
                "alert": _tone([(990, 0.07), (990, 0.07)], 0.14, "square", gain=0.14),
                "isolate": _tone([(330, 0.18)], 0.18, decay=4, gain=0.3),
                "decoy": _tone([(660, 0.06), (440, 0.06), (660, 0.1)], 0.22, "square", gain=0.16),
                "win_red": _tone([(392, 0.12), (523, 0.12), (659, 0.12), (784, 0.35)], 0.7, gain=0.3),
                "win_blue": _tone([(523, 0.12), (440, 0.12), (349, 0.12), (523, 0.35)], 0.7, gain=0.3),
                "click": _tone([(1400, 0.025)], 0.025, gain=0.15),
            }
            self.sounds = {k: pygame.sndarray.make_sound(v) for k, v in spec.items()}
            self.ok = True
        except Exception:          # no audio device (headless, CI) or no mixer support
            self.ok = False

    def play(self, name):
        if not (self.ok and self.enabled):
            return
        s = self.sounds.get(name)
        if s is not None:
            s.set_volume(self.volume)
            s.play()
