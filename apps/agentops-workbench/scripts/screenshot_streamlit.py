r"""Drive the running Streamlit UI via headless Chrome and capture screenshots.

Requires the system Google Chrome (or Chromium) -- Playwright drives it via
channel="chrome", so no playwright-bundled browser download is needed.
An ephemeral profile is created per launch.

Usage:
    uv run python scripts/screenshot_streamlit.py

Captures:
    docs/screenshots/01_landing.png            — Streamlit landing (default task pre-loaded)
    docs/screenshots/02_after_submit.png       — LangGraph checkpointing query result
    docs/screenshots/03_sqlite_query.png       — SQLite vs Postgres comparison query
    docs/screenshots/04_unrelated_query.png    — Off-topic query (refusal path)
    docs/screenshots/05_debug_endpoint.png     — /_debug/retrieve JSON response
    docs/screenshots/06_metrics_endpoint.png   — /_debug/metrics live dashboard

Notes:
- Set AGENTOPS_SCREENSHOT_NO_SANDBOX=1 only when running as root
  (some CI images). Default uses Chrome's sandbox.
- Wait strategy is domcontentloaded (Streamlit's persistent /_stcore/stream
  WebSocket never reaches networkidle).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


STREAMLIT_URL = "http://127.0.0.1:8501/"
API_BASE = "http://127.0.0.1:8000"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)


SCENARIOS = [
    # (filename_stem, task_text, output_filename)
    (
        "02_after_submit",
        "How do I configure LangGraph checkpointing with PostgreSQL?",
    ),
    (
        "03_sqlite_query",
        "When should I use SqliteCheckpointer instead of PostgresCheckpointer?",
    ),
    (
        "04_unrelated_query",
        "How do I bake sourdough bread?",
    ),
]


def submit_and_capture(page, task_text: str, out_path: Path) -> None:
    """Type the task into the textarea, click Submit, wait for the answer, screenshot."""
    page.wait_for_selector("textarea", timeout=10_000)
    textarea = page.locator("textarea").first
    textarea.click()
    # Clear via select-all + delete (Streamlit text_area can hold multiline)
    textarea.press("ControlOrMeta+A")
    textarea.press("Delete")
    textarea.fill(task_text)
    page.wait_for_timeout(400)

    submit = page.get_by_role("button", name="Submit")
    submit.scroll_into_view_if_needed()
    submit.click()

    # Wait for the run row to appear with a non-empty Answer section.
    page.wait_for_selector("h3:has-text('Answer')", timeout=20_000)
    page.wait_for_timeout(2000)  # let the answer render
    page.screenshot(path=str(out_path), full_page=True)
    print(f"  saved: {out_path.relative_to(OUT_DIR.parent.parent)}")


def main() -> None:
    with sync_playwright() as pw:
        # --no-sandbox is needed when running as root (some CI images). Opt-in
        # via env var; default is the safer Chrome sandbox.
        args = ["--disable-dev-shm-usage"]
        if os.environ.get("AGENTOPS_SCREENSHOT_NO_SANDBOX") == "1":
            args.append("--no-sandbox")
        # channel="chrome" uses the system Chrome at /Applications/Google Chrome.app
        # (macOS), /usr/bin/google-chrome (Linux), or the Chrome install on
        # Windows. An ephemeral profile is created per launch so we never
        # collide with the user's logged-in session.
        browser = pw.chromium.launch(
            channel="chrome",
            headless=True,
            args=args,
        )
        ctx = browser.new_context(viewport={"width": 1280, "height": 1100}, device_scale_factor=2)
        page = ctx.new_page()

        # 1) Landing page.
        page.goto(STREAMLIT_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("textarea", timeout=10_000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT_DIR / "01_landing.png"), full_page=True)
        print(f"  saved: docs/screenshots/01_landing.png")

        # 2-4) Each scenario: re-load the page fresh, submit, screenshot.
        for stem, task in SCENARIOS:
            page.goto(STREAMLIT_URL, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_selector("textarea", timeout=10_000)
            page.wait_for_timeout(800)
            submit_and_capture(page, task, OUT_DIR / f"{stem}.png")

        browser.close()

    # 5) The /_debug/retrieve endpoint — not a browser screenshot, but a
    # machine-readable capture of the exact JSON the API returns for the
    # default task. Render it as a styled HTML page and screenshot that.
    with sync_playwright() as pw:
        # --no-sandbox is needed when running as root (some CI images). Opt-in
        # via env var; default is the safer Chrome sandbox.
        args = ["--disable-dev-shm-usage"]
        if os.environ.get("AGENTOPS_SCREENSHOT_NO_SANDBOX") == "1":
            args.append("--no-sandbox")
        # channel="chrome" uses the system Chrome at /Applications/Google Chrome.app
        # (macOS), /usr/bin/google-chrome (Linux), or the Chrome install on
        # Windows. An ephemeral profile is created per launch so we never
        # collide with the user's logged-in session.
        browser = pw.chromium.launch(
            channel="chrome",
            headless=True,
            args=args,
        )
        ctx = browser.new_context(viewport={"width": 1280, "height": 1100}, device_scale_factor=2)
        page = ctx.new_page()

        task = "How do I configure LangGraph checkpointing with PostgreSQL?"
        with urllib.request.urlopen(
            f"{API_BASE}/_debug/retrieve?task={urllib.parse.quote(task)}", timeout=10
        ) as resp:
            payload = json.loads(resp.read())

        # 5a) Fetch /_debug/metrics JSON so the screenshot reflects live data.
        with urllib.request.urlopen(
            f"{API_BASE}/_debug/metrics", timeout=10
        ) as resp:
            metrics_payload = json.loads(resp.read())

        retrieve_html = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Debug retrieve</title>
<style>
  body {{ font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
          background: #f6f7f9; margin: 0; padding: 32px; color: #1f2937; }}
  h1 {{ font-size: 22px; margin: 0 0 16px; }}
  pre {{ background: #fff; border: 1px solid #d1d5db; border-radius: 8px;
         padding: 18px; font-size: 13px; line-height: 1.5; overflow: auto;
         white-space: pre-wrap; word-wrap: break-word; }}
  .matched {{ color: #047857; font-weight: 600; }}
  .unmatched {{ color: #b91c1c; font-weight: 600; }}
  .doc {{ margin: 6px 0; }}
  .stem {{ color: #6b21a8; font-weight: 600; }}
</style></head>
<body>
<h1>GET /_debug/retrieve?task={urllib.parse.quote(task)}</h1>
<pre>{json.dumps(payload, indent=2)}</pre>
</body></html>"""
        page.set_content(retrieve_html)
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT_DIR / "05_debug_endpoint.png"), full_page=True)
        print(f"  saved: docs/screenshots/05_debug_endpoint.png")

        browser.close()

    # 6) /_debug/metrics page -- live, JSON-formatted, web-debuggable.
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(viewport={"width": 1280, "height": 1100}, device_scale_factor=2)
        page = ctx.new_page()

        with urllib.request.urlopen(f"{API_BASE}/_debug/metrics", timeout=10) as resp:
            metrics_payload = json.loads(resp.read())

        metrics_html = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Debug metrics</title>
<style>
  body {{ font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
          background: #f6f7f9; margin: 0; padding: 32px; color: #1f2937; }}
  h1 {{ font-size: 22px; margin: 0 0 8px; }}
  h2 {{ font-size: 16px; margin: 20px 0 6px; color: #4338ca; }}
  pre {{ background: #fff; border: 1px solid #d1d5db; border-radius: 8px;
         padding: 18px; font-size: 13px; line-height: 1.5; overflow: auto;
         white-space: pre-wrap; word-wrap: break-word; }}
  .caveat {{ background: #fef3c7; border-color: #f59e0b;
             padding: 12px 16px; border-radius: 6px; margin-top: 8px;
             font-size: 12px; line-height: 1.5; }}
</style></head>
<body>
<h1>GET /_debug/metrics</h1>
<p style='color:#6b7280;font-size:12px;margin:0 0 16px'>Live, recomputed on every request. Pass <code>AGENTOPS_PRICING_JSON</code> to override MODEL_PRICING.</p>
<pre>{json.dumps(metrics_payload, indent=2)}</pre>

<h2>Why is cost_usd 0?</h2>
<div class='caveat'>{metrics_payload["caveats"]["cost_usd"]}</div>

<h2>Why is tool_calls 0?</h2>
<div class='caveat'>{metrics_payload["caveats"]["tool_calls"]}</div>
</body></html>"""
        page.set_content(metrics_html)
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT_DIR / "06_metrics_endpoint.png"), full_page=True)
        print(f"  saved: docs/screenshots/06_metrics_endpoint.png")

        browser.close()


if __name__ == "__main__":
    main()
