"""LocalFakeAdapter — deterministic scripted responses for CI / unit tests.

When `provider=local-fake`, this adapter synthesizes an answer by
re-running the same retrieval the real graph uses, then composing a
"looks-like-a-real-LLM" response from the retrieved docs. Output
structure mirrors what a real model would produce (introduction + quoted
passage + follow-on detail + source attribution), so the Streamlit
debug surface looks like an actual agent ran — not a string-lookup.

For CI / held-out benchmarks where exact text matters, the script
directory `fixtures/llm/scripts/` still holds the canned responses
and the `_pick_scripted_response` path remains available (call with
`use_synthesis=False`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .adapter import ChatResult, LLMAdapter, Usage


class LocalFakeAdapter(LLMAdapter):
    provider = "local-fake"
    model = "local-fake-v1"

    def __init__(self, scripts_dir: Path | None = None) -> None:
        self._scripts_dir = scripts_dir or (
            Path(__file__).resolve().parent.parent.parent.parent
            / "fixtures"
            / "llm"
            / "scripts"
        )
        self._counter = 0
        self._script: list[dict[str, str]] = []
        self._load_script("default.jsonl")
        self._synth_counter = 0

    def _load_script(self, name: str) -> None:
        path = self._scripts_dir / name
        if not path.exists():
            self._script = [
                {"role": "assistant", "content": "local-fake default response"}
            ]
            return
        self._script = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        if not self._script:
            self._script = [
                {"role": "assistant", "content": "local-fake default response"}
            ]

    @staticmethod
    def _extract_retrieval_block(messages: list[dict[str, str]]) -> str:
        """Pull the "Retrieved docs:" block out of the user prompt.

        The fixed graph builds a prompt of the form
            "Retrieved docs:\n{body}\n\nTask: {task}"
        for the answer step. We parse out the body so we can synthesize
        a response from the actual retrieved content.
        """
        joined = "\n".join(m.get("content", "") for m in messages)
        m = re.search(r"Retrieved docs:\n(.*?)\n\nTask:", joined, flags=re.DOTALL)
        return m.group(1) if m else ""

    @staticmethod
    def _extract_task(messages: list[dict[str, str]]) -> str:
        joined = "\n".join(m.get("content", "") for m in messages)
        m = re.search(r"\n\nTask:\s*(.+?)\s*$", joined, flags=re.DOTALL)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _parse_doc_blocks(retrieval: str) -> list[tuple[str, str]]:
        """Split "Retrieved docs:\n[stem]: snippet\n\n--\n\n[stem]: ..." into (stem, body)."""
        if not retrieval or retrieval == "(no relevant docs found)":
            return []
        blocks: list[tuple[str, str]] = []
        for chunk in retrieval.split("\n\n--\n\n"):
            head, _, body = chunk.partition("]: ")
            if not body:
                continue
            stem = head.lstrip("[").rstrip()
            blocks.append((stem, body))
        return blocks

    @staticmethod
    def _synthesize(task: str, docs: list[tuple[str, str]]) -> str:
        """Compose a realistic-looking answer from the retrieved docs."""
        if not docs:
            return (
                "I searched the corpus and found no direct match. "
                "Could you provide the project name or specific error message?"
            )

        # Pick the first doc as the lead; mention any others as supporting.
        lead_stem, lead_body = docs[0]
        # Clean up the snippet: drop the file-path header if present,
        # collapse whitespace, keep the first ~6 lines of substance.
        lead_text = re.sub(r"\s+", " ", lead_body).strip()
        # Pull a representative passage (60-180 chars after the title).
        passage = lead_text[:180].rsplit(".", 1)[0] + "."

        intro = (
            "Based on the corpus, here's what I found for your question:\n\n"
            f"**{lead_stem}**\n\n"
        )
        quoted = f"> {passage}\n\n"
        followon_lines: list[str] = []
        if len(docs) > 1:
            extras = ", ".join(stem for stem, _ in docs[1:])
            followon_lines.append(f"See also: {extras}.")
        followon_lines.append(
            f"Source: {lead_stem} (fixture doc). "
            "Real provider would quote verbatim from the upstream "
            "langgraph docs; local-fake synthesizes a shorter summary."
        )
        followon = "\n".join(followon_lines)

        return intro + quoted + followon

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kw: Any,
    ) -> ChatResult:
        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        prompt_tokens = max(1, prompt_chars // 4)

        # Synthesize from the retrieved docs so the response looks like
        # a real model reading the corpus, not a canned line.
        retrieval = self._extract_retrieval_block(messages)
        docs = self._parse_doc_blocks(retrieval)
        task = self._extract_task(messages)
        content = self._synthesize(task, docs)

        completion_tokens = max(1, len(content) // 4)

        usage = Usage(
            provider=self.provider,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=0.0,
        )
        self._last_usage = usage
        return ChatResult(content=content, usage=usage)
