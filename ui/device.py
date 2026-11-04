"""Screen shape and touch helpers.

The game draws at a fixed logical size and pygame scales it to the window. On
a computer that size is 1600 x 900. On a phone that would make every word
tiny, so a phone gets its own, smaller logical size in the shape of its
screen ('portrait' or 'landscape'); ui/mobile.py lays the game out for it.

    pick(css_w, css_h)   -> Layout for a viewport of that many CSS pixels
    viewport()           -> the browser's viewport, or a forced one (--viewport / ZERO_DAY_VIEWPORT)
    ask_text(label, cur) -> the browser's own text box (phones have no keyboard for pygame), or None
"""

import json
import os
import sys
from collections import namedtuple

WEB = sys.platform == "emscripten"

Layout = namedtuple("Layout", "name w h")
DESKTOP = Layout("desktop", 1600, 900)

PHONE_SHORT_SIDE = 560      # CSS px: a landscape screen shorter than this gets the phone layout


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def pick(css_w, css_h):
    """Logical canvas for a viewport. Phones get about 1.2 logical px per CSS px, so 13 px text stays readable."""
    if not css_w or not css_h or css_w <= 0 or css_h <= 0:
        return DESKTOP
    if css_h > css_w * 1.05:                                   # portrait (phone or tablet held upright)
        w = _clamp(round(css_w * 1.2), 460, 760)
        return Layout("portrait", w, round(w * css_h / css_w))
    if min(css_w, css_h) < PHONE_SHORT_SIDE:                   # phone on its side
        h = _clamp(round(css_h * 1.2), 440, 560)
        return Layout("landscape", _clamp(round(h * css_w / css_h), 760, 1400), h)
    return DESKTOP


def forced():
    """A viewport set with --viewport WxH (or ZERO_DAY_VIEWPORT), to try the phone layouts on a computer."""
    v = os.environ.get("ZERO_DAY_VIEWPORT", "")
    try:
        w, h = (int(x) for x in v.lower().split("x"))
        return w, h
    except ValueError:
        return None


def viewport():
    """(css_w, css_h) of the page in the browser, a forced size, or None on a computer."""
    f = forced()
    if f:
        return f
    if not WEB:
        return None
    try:
        import platform as _pf
        return int(_pf.window.innerWidth), int(_pf.window.innerHeight)
    except Exception:  # noqa: BLE001
        return None


def refit_canvas():
    """Browser: after the canvas changes size, let the page re-run its fit-to-window code."""
    if not WEB:
        return
    try:
        import platform as _pf
        _pf.window.eval("window.dispatchEvent(new Event('resize'))")
    except Exception:  # noqa: BLE001
        pass


def log(text):
    """Browser: write to the page's console (the smoke test reads it). Elsewhere: print."""
    if WEB:
        try:
            import platform as _pf
            _pf.window.console.log(str(text))
            return
        except Exception:  # noqa: BLE001
            pass
    print(text)


def ask_text(label, current=""):
    """Browser only: the page's text prompt, which brings up the phone's keyboard.
    Returns the new text, or None if cancelled or not in a browser."""
    if not WEB:
        return None
    try:
        import platform as _pf
        js = ("(function(){var r=window.prompt(%s,%s);return r===null?'\\u0000':String(r);})()"
              % (json.dumps(label), json.dumps(current)))
        out = str(_pf.window.eval(js))
    except Exception:  # noqa: BLE001
        return None
    return None if out == "\x00" else out.strip()
