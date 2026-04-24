"""Playwright-driven reproducer for the seek-then-play bug on preview.html.

Opens the page, waits for the audio to be playable, then:
  1. Dumps initial audio state
  2. Sets audio.currentTime = 60  (simulating a click on the native bar)
  3. Dumps state after seek
  4. Calls audio.play()
  5. Samples audio.currentTime every 500ms for 4 seconds
  6. Prints the whole trace

If play is "grabbing it back", we'll see audio.currentTime drop to 0 at some
sample and we'll know exactly when.
"""

from __future__ import annotations

import time
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/preview.html"


def dump_state(page, label):
    s = page.evaluate("""() => {
        const a = document.getElementById('audio');
        return {
            currentTime: a.currentTime,
            duration: a.duration,
            paused: a.paused,
            readyState: a.readyState,
            networkState: a.networkState,
            error: a.error ? { code: a.error.code, message: a.error.message } : null,
            src: a.currentSrc,
        };
    }""")
    print(f"[{label}] {s}")
    return s


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path="/Users/julian/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        )
        ctx = browser.new_context()
        page = ctx.new_page()

        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(f"[console:{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: console_msgs.append(f"[pageerror] {err}"))

        print(f"-> Opening {URL}")
        page.goto(URL)

        # Wait for status.json fetch + audio src set + metadata loaded
        print("-> Waiting for audio metadata...")
        page.wait_for_function(
            "() => document.getElementById('audio').readyState >= 1",
            timeout=30_000,
        )

        dump_state(page, "after-load")

        # SEEK to 60s via the same path the native control would use
        print("\n-> Programmatically setting audio.currentTime = 60 (like a native-bar click)")
        page.evaluate("() => { document.getElementById('audio').currentTime = 60; }")
        time.sleep(0.5)
        dump_state(page, "after-seek")

        # Wait for seeked event to definitely fire
        page.wait_for_function(
            "() => Math.abs(document.getElementById('audio').currentTime - 60) < 1",
            timeout=5_000,
        )
        dump_state(page, "after-seeked-confirmed")

        # PLAY
        print("\n-> Calling audio.play()")
        page.evaluate("() => document.getElementById('audio').play()")
        time.sleep(0.3)
        dump_state(page, "right-after-play")

        # Sample every 500ms for 4 seconds
        print("\n-> Sampling currentTime for 4s:")
        for i in range(8):
            time.sleep(0.5)
            dump_state(page, f"t+{(i+1)*0.5:.1f}s")

        print("\n-> Console messages during run:")
        for m in console_msgs:
            print("   " + m)

        browser.close()


if __name__ == "__main__":
    main()
