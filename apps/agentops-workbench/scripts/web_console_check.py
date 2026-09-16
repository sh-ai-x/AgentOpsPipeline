"""Headless verification loop for the AgentOps Wiki web UI.

Captures every console error, page error, and network failure across
six end-to-end scenarios. Use this in CI or before each release to
catch regressions without a real browser.

Prereqs (one-time):
  uv pip install playwright
  uv run playwright install chromium

Run while the dev stack is up:
  API=http://127.0.0.1:8000  WEB=http://localhost:3000 \
  uv run python scripts/web_console_check.py

Exits 0 when every scenario is clean. Non-zero on the first console
error / page error / unexpected network failure.

The Next.js dev rewrite is expected to proxy /api/* to the FastAPI
backend on AGENTOPS_API_BASE (default http://127.0.0.1:8000).
"""
from __future__ import annotations

import os
import sys
from playwright.sync_api import sync_playwright, ConsoleMessage, Page

WEB_URL = os.environ.get("WEB_URL", "http://localhost:3000/")

# Expected non-error responses we filter out — they're part of the
# normal dev-mode probe lifecycle, not real failures.
EXPECTED_401_PATHS = ("/v1/wiki/search",)


def main() -> int:
    issues: list[tuple[str, str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        page.on("console", _on_console(issues))
        page.on("pageerror", _on_pageerror(issues))
        page.on("response", _on_response(issues))

        # 1. Initial load + dev-mode auto-mint
        print(">>> Scenario 1: initial load + auto-mint")
        page.goto(WEB_URL, wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(800)
        status = page.locator(".status").first.inner_text()
        assert "dev-mode" in status.lower() or "signed in as" in status.lower(), status
        print(f"  status bar: {status!r}")

        # 2. Upload a tiny corpus via fetch (real picker needs a user)
        print(">>> Scenario 2: upload a tiny corpus")
        files = [{
            "path": "demo.md",
            "content": (
                "# Demo\n"
                "Postgres writes durable checkpoints to a postgres table.\n"
                "Postgres checkpointing uses PostgresSaver internally.\n"
            ),
            "mtime": 0,
        }]
        idx = page.evaluate(
            """async (files) => {
                const tk = await fetch('/api/v1/auth/dev-token?principal_id=demo-user');
                const {token} = await tk.json();
                const r = await fetch('/api/v1/wiki/index-files', {
                    method: 'POST',
                    headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                    body: JSON.stringify({files}),
                });
                return {status: r.status, body: await r.json()};
            }""",
            files,
        )
        assert idx["status"] == 200, idx
        cid = idx["body"]["corpus_id"]
        print(f"  corpus_id={cid} doc_count={idx['body']['doc_count']}")

        # 3. Search and assert the five AC3 trust fields are present
        print(">>> Scenario 3: search")
        search = page.evaluate(
            """async (cid) => {
                const tk = await fetch('/api/v1/auth/dev-token?principal_id=demo-user');
                const {token} = await tk.json();
                const r = await fetch(`/api/v1/wiki/search?corpus_id=${cid}&q=postgres+checkpointing&top_k=3`, {
                    headers: {'Authorization': 'Bearer ' + token},
                });
                return {status: r.status, body: await r.json()};
            }""",
            cid,
        )
        assert search["status"] == 200
        for h in search["body"]["results"]:
            for field in ("ref_id", "source_path", "score", "coverage", "mtime",
                          "contributing_terms", "evidence_span", "match_offsets"):
                assert field in h, f"missing AC3 field: {field}"
        print(f"  hits={len(search['body']['results'])} all 5 AC3 fields present")

        # 4. QA — the three published metrics must surface
        print(">>> Scenario 4: QA")
        qa = page.evaluate(
            """async (cid) => {
                const tk = await fetch('/api/v1/auth/dev-token?principal_id=demo-user');
                const {token} = await tk.json();
                const r = await fetch('/api/v1/wiki/qa', {
                    method: 'POST',
                    headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                    body: JSON.stringify({corpus_id: cid, query: 'what is postgres', top_k: 2}),
                });
                return {status: r.status, body: await r.json()};
            }""",
            cid,
        )
        assert qa["status"] == 200, qa
        for field in ("query", "corpus_id", "answer", "overall_rouge_l_f1",
                      "citation_recall", "citation_precision", "sentences", "hits"):
            assert field in qa["body"], f"missing QA field: {field}"
        print(f"  QA shape OK; answer='{qa['body']['answer'][:60]}...'")

        # 5. Reload — dev-mode auto-mint must fire again
        print(">>> Scenario 5: reload")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(500)
        status2 = page.locator(".status").first.inner_text()
        assert "dev-mode" in status2.lower() or "signed in as" in status2.lower(), status2
        print(f"  after reload status: {status2!r}")

        # 6. Type into the first visible input to exercise React event handlers
        print(">>> Scenario 6: input interaction")
        inputs = page.locator("input:visible")
        if inputs.count() > 0:
            inputs.first.fill("test-typing")
            typed = inputs.first.input_value()
            print(f"  typed into first visible input -> {typed!r}")
        else:
            print("  no visible inputs (dev-mode status bar only)")

        browser.close()

    # Report
    print("\n" + "=" * 70)
    print(f"TOTAL ISSUES: {len(issues)}")
    print("=" * 70)
    for kind, sev, msg in issues:
        print(f"  [{kind}/{sev}] {msg[:200]}")
    if issues:
        return 1
    print("ALL SCENARIOS CLEAN")
    return 0


def _on_console(issues: list[tuple[str, str, str]]):
    def _h(msg: ConsoleMessage) -> None:
        if msg.type in ("error", "warning"):
            issues.append(("console", msg.type, msg.text))
    return _h


def _on_pageerror(issues: list[tuple[str, str, str]]):
    def _h(err: object) -> None:
        issues.append(("pageerror", "uncaught", str(err)))
    return _h


def _on_response(issues: list[tuple[str, str, str]]):
    def _h(resp) -> None:
        if resp.status < 400:
            return
        if any(p in resp.url for p in EXPECTED_401_PATHS) and resp.status == 401:
            return
        if ".well-known/" in resp.url:
            return
        issues.append(("network", str(resp.status), f"{resp.request.method} {resp.url}"))
    return _h


if __name__ == "__main__":
    sys.exit(main())
