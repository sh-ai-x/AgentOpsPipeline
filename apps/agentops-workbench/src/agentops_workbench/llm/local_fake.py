"""LocalFakeAdapter — deterministic scripted responses for CI / unit tests.

Reads scripts from `fixtures/llm/scripts/<script_name>.jsonl`. Each line is
`{"role": "...", "content": "..."}`; lines are consumed in order.
`local-fake-v1` (the default model) reads `fixtures/llm/scripts/default.jsonl`.
"""
from __future__ import annotations

import json
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

    def _load_script(self, name: str) -> None:
        path = self._scripts_dir / name
        if not path.exists():
            # Fallback: minimal canned response so import-time smoke works
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

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kw: Any,
    ) -> ChatResult:
        # Token counting is a deterministic mock: 1 token per 4 chars
        prompt_chars = sum(len(m.get("content", "")) for m in messages)
        prompt_tokens = max(1, prompt_chars // 4)

        idx = self._counter % len(self._script)
        self._counter += 1
        scripted = self._script[idx]
        content = scripted.get("content", "")
        completion_tokens = max(1, len(content) // 4)

        return ChatResult(
            content=content,
            usage=Usage(
                provider=self.provider,
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_usd=0.0,
            ),
        )
