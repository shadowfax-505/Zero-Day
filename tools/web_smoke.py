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


def boot(browser, name):
    page = browser.new_page(viewport={"width": 1280, "height": 760})
    log = []
    page.on("console", lambda m: log.append(m.text))
    page.on("pageerror", lambda e: log.append(f"PAGEERROR {e}"))
    page.goto(f"{PAGE}/?relay={RELAY_WS}")
    end = time.time() + 180
    while time.time() < end:
        if any("Zero Day running" in line for line in log):
            break
        page.mouse.click(640, 380)          # pygbag waits for a click before it starts (audio rules)
        page.wait_for_timeout(2000)
    else:
        page.screenshot(path=f"{OUT}/{name}-stuck.png")
        print("\n".join(log[-60:]))
        raise SystemExit(f"{name}: the game never started")
    page.wait_for_timeout(3000)
    page.screenshot(path=f"{OUT}/{name}-menu.png")
    return page, log


def key(page, k, n=1, wait=250):
    for _ in range(n):
        page.keyboard.press(k)
        page.wait_for_timeout(wait)


def errors(log):
    return [line for line in log if "Traceback" in line or "Error" in line and "PAGEERROR" in line]


def main():
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()

        page, log = boot(browser, "ai")
        key(page, "Enter")                   # first menu item: AI VS AI
        page.wait_for_timeout(25000)
        page.screenshot(path=f"{OUT}/ai-match.png")
        print("---- AI vs AI console ----")
        print("\n".join(log[-40:]))
        if errors(log):
            ok = False
            print("AI vs AI page logged errors")

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
