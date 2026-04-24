"""Take a screenshot of preview.html in its loaded state and print what's in
the viewer (video src, img src, hidden flags, caption)."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/preview.html"
CHROMIUM = "/Users/julian/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROMIUM)
        page = browser.new_page(viewport={"width": 1600, "height": 900})

        errors = []
        page.on("console", lambda m: errors.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: errors.append(f"[err] {e}"))
        page.on("requestfailed", lambda r: errors.append(f"[404?] {r.url} ({r.failure})"))

        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_function(
            "() => document.getElementById('audio').readyState >= 1 && document.getElementById('tabs').children.length > 0",
            timeout=20_000,
        )
        page.wait_for_timeout(1500)  # let viewer populate

        viewer = page.evaluate("""() => {
            const img = document.getElementById('still');
            const vid = document.getElementById('vid');
            const cap = document.getElementById('caption');
            return {
                stillSrc: img.getAttribute('src'),
                stillHidden: img.hidden,
                vidSrc: vid.getAttribute('src'),
                vidHidden: vid.hidden,
                vidReadyState: vid.readyState,
                vidPaused: vid.paused,
                vidError: vid.error ? vid.error.code : null,
                caption: cap.innerText,
                audioTime: document.getElementById('audio').currentTime,
                tabsCount: document.getElementById('tabs').children.length,
                blockCount: document.getElementById('timeline').children.length,
            };
        }""")
        print("viewer state:", viewer)
        print("console/errors:")
        for e in errors:
            print(" ", e)
        page.screenshot(path="/tmp/preview.png", full_page=True)
        print("screenshot -> /tmp/preview.png")
        browser.close()


if __name__ == "__main__":
    main()
