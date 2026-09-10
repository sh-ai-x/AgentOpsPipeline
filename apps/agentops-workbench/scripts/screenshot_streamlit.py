"""Drive the running Streamlit UI via headless Chrome and capture screenshots.

Usage:
    uv run python scripts/screenshot_streamlit.py

Captures:
    docs/screenshots/01_landing.png            — Streamlit landing (default task pre-loaded)
    docs/screenshots/02_after_submit.png       — After clicking Submit, full result panel
"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


STREAMLIT_URL = "http://127.0.0.1:8501/"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as pw:
        # Use the system Chrome (Google Chrome.app) so we don't depend on
        # playwright's bundled chromium download succeeding.
        browser = pw.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(viewport={"width": 1280, "height": 1100}, device_scale_factor=2)
        page = ctx.new_page()
        page.goto(STREAMLIT_URL, wait_until="networkidle", timeout=30_000)

        # 1) Landing page (default task pre-loaded in the text area).
        page.wait_for_selector("textarea", timeout=10_000)
        page.wait_for_timeout(1500)  # let streamlit settle
        landing = OUT_DIR / "01_landing.png"
        page.screenshot(path=str(landing), full_page=True)
        print(f"  saved: {landing.relative_to(OUT_DIR.parent.parent)}")

        # 2) Click Submit and capture the result panel.
        submit = page.get_by_role("button", name="Submit")
        submit.scroll_into_view_if_needed()
        submit.click()

        # Wait for the Answer markdown to appear.
        page.wait_for_selector("h3:has-text('Answer')", timeout=20_000)
        page.wait_for_timeout(1500)
        result = OUT_DIR / "02_after_submit.png"
        page.screenshot(path=str(result), full_page=True)
        print(f"  saved: {result.relative_to(OUT_DIR.parent.parent)}")

        browser.close()


if __name__ == "__main__":
    main()
