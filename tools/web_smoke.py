"""Smoke test for the browser build (run by .github/workflows/web.yml).

Opens the built page in headless Chromium, starts an AI vs AI match, then a
second page hosts an online game through a local relay and checks the relay
sees the room. Screenshots go to web-smoke/. Exits non-zero on failure.

    python tools/web_smoke.py http://localhost:8000 ws://127.0.0.1:8765 http://127.0.0.1:8765
"""

import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

PAGE, RELAY_WS, RELAY_HTTP = sys.argv[1:4]
OUT = "web-smoke"
os.makedirs(OUT, exist_ok=True)


def boot(browser, name, phone=False):
    if phone:      # a phone held upright, with a touch screen
        page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
                                has_touch=True)
    else:
        page = browser.new_page(viewport={"width": 1280, "height": 760})
    log = []
    page.on("console", lambda m: log.append(m.text))
    page.on("pageerror", lambda e: log.append(f"PAGEERROR {e}"))
    page.goto(f"{PAGE}/?relay={RELAY_WS}")
    end = time.time() + 180
    while time.time() < end:
        if any("Zero Day running" in line for line in log):
            break
        page.mouse.click(*((195, 420) if phone else (640, 380)))   # pygbag waits for a click before it starts (audio rules)
        page.wait_for_timeout(2000)
    else:
        page.screenshot(path=f"{OUT}/{name}-stuck.png")
        print("\n".join(log[-60:]))
        print("---- page text ----")
        print(page.evaluate("document.body.innerText")[-4000:])
        raise SystemExit(f"{name}: the game never started")
    page.wait_for_timeout(3000)
    page.screenshot(path=f"{OUT}/{name}-menu.png")
    return page, log


def key(page, k, n=1, wait=250):
    for _ in range(n):
        page.keyboard.press(k)
        page.wait_for_timeout(wait)


def canvas_box(page):
    return page.evaluate("(() => { const r = document.querySelector('canvas').getBoundingClientRect();"
                         " return [r.x, r.y, r.width, r.height]; })()")


def layout(log):
    """('portrait', 468, 1013) from the game's last 'Zero Day layout ...' console line."""
    lines = [line for line in log if line.startswith("Zero Day layout ")]
    if not lines:
        return None
    name, size = lines[-1].split()[3:5]
    w, h = size.split("x")
    return name, int(w), int(h)


def tap(page, log, x, y, wait=800):
    """Touch the screen at game pixel (x, y) of the current layout."""
    _, w, h = layout(log)
    b = canvas_box(page)
    page.touchscreen.tap(b[0] + x / w * b[2], b[1] + y / h * b[3])
    page.wait_for_timeout(wait)


def phone_test(browser):
    """Portrait phone: the phone layout is picked, touch starts a match and opens the pause menu
    (no keyboard), and turning the phone switches to the landscape layout."""
    ok = True
    page, log = boot(browser, "phone", phone=True)
    lay = layout(log)
    print("phone layout:", lay, "canvas:", canvas_box(page))
    if not lay or lay[0] != "portrait":
        print("a portrait phone did not get the portrait layout")
        return False
    _, w, h = lay
    b = canvas_box(page)
    if b[2] < 390 * 0.9 or b[0] < -1 or b[0] + b[2] > 391:
        ok = False
        print("the canvas does not fill the phone's width")
    n = 5                                                   # menu items in the browser (no QUIT)
    tap(page, log, w // 2, h - 36 - n * 58 + 25, wait=20000)    # 01 AI VS AI (ui/mobile.py menu_geometry)
    page.screenshot(path=f"{OUT}/phone-portrait-match.png")
    bar_y = h - 64 + 8 + 25
    tap(page, log, w - 6 - (w - 36) // 10, bar_y)             # MENU, the last button in the bottom bar
    page.screenshot(path=f"{OUT}/phone-portrait-pause.png")
    if not any("pause menu open" in line for line in log):
        ok = False
        print("tapping MENU did not open the pause menu")
    page.set_viewport_size({"width": 844, "height": 390})     # turn the phone
    page.wait_for_timeout(3000)
    lay = layout(log)
    print("after turning:", lay, "canvas:", canvas_box(page))
    page.screenshot(path=f"{OUT}/phone-landscape-pause.png")
    if not lay or lay[0] != "landscape":
        ok = False
        print("turning the phone did not switch to the landscape layout")
    print("---- phone console ----")
    print("\n".join(log[-30:]))
    if errors(log):
        ok = False
        print("phone page logged errors")
    return ok


def errors(log):
    return [line for line in log if "Traceback" in line or "crashed" in line or line.startswith("PAGEERROR")]


def main():
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()

        page, log = boot(browser, "ai")
        key(page, "Enter")                   # first menu item: AI VS AI
        page.wait_for_timeout(25000)
        page.screenshot(path=f"{OUT}/ai-match.png")
        # view switching: number keys, then clicking the RED / FULL / BLUE buttons in the top bar
        key(page, "1", wait=800)
        key(page, "3", wait=800)
        box = page.evaluate("(() => { const r = document.querySelector('canvas').getBoundingClientRect();"
                            " return [r.x, r.y, r.width, r.height]; })()")
        for x, label in ((1416, "red"), (1480, "full")):   # paper theme buttons, in game pixels (1600x900)
            page.mouse.click(box[0] + x / 1600 * box[2], box[1] + 32 / 900 * box[3])
            page.wait_for_timeout(800)
        page.screenshot(path=f"{OUT}/ai-view-switch.png")
        seen = [line for line in log if line.startswith("view: ")]
        print("view switches:", seen)
        if seen[-4:] != ["view: red", "view: blue", "view: red", "view: full"]:
            ok = False
            print("switching the view in AI vs AI did not work")
        print("---- AI vs AI console ----")
        print("\n".join(log[-40:]))
        if errors(log):
            ok = False
            print("AI vs AI page logged errors")

        if not phone_test(browser):
            ok = False

        page2, log2 = boot(browser, "online")
        key(page2, "ArrowDown", 3)
        key(page2, "Enter")                  # PLAY ONLINE
        page2.wait_for_timeout(4000)
        page2.screenshot(path=f"{OUT}/online-lobby.png")
        key(page2, "Enter")                  # the cursor starts on HOST A GAME
        found = ""
        for _ in range(20):
            page2.wait_for_timeout(1000)
            found = urllib.request.urlopen(RELAY_HTTP).read().decode()
            if "1 room(s)" in found:
                break
        page2.screenshot(path=f"{OUT}/online-hosting.png")
        print("---- online console ----")
        print("\n".join(log2[-40:]))
        print("relay says:", found.strip())
        if "1 room(s)" not in found or errors(log2):
            ok = False
            print("hosting through the relay did not work")
        browser.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
