"""OpenTelemetry exporter + redaction.

Step 6 ships a minimal OTel-like span record + a redaction pass that strips
synthetic credentials from trace payloads before they hit disk.

Per the proposal:
  - OpenTelemetry only (no LangSmith)
  - Spans around model calls, tool calls, state transitions, failures
  - Redact api_key, authorization, bearer, and known credential fields
"""
from __future__ import annotations

import json
import time
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

REDACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # key=value forms
    ("api_key", re.compile(r"(?i)(api[_-]?key)\s*[:=]\s*[^\s,;}]+")),
    ("authorization", re.compile(r"(?i)(authorization)\s*[:=]\s*[^\s,;}]+")),
    ("password", re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*[^\s,;}]+")),
    # Bearer / Authorization: Bearer <token>
    ("bearer", re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._\-]+")),
    # JWT-shape tokens (header.payload.signature)
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")),
    # sk-cp-... and sk-... keys (any non-trivial length)
    ("secret_key", re.compile(r"sk-(?:cp-)?[A-Za-z0-9_-]{4,}")),
)


def redact(value: Any) -> Any:
    """Recursively redact credential substrings in strings / dicts / lists."""
    if isinstance(value, str):
        out = value
        for label, pattern in REDACT_PATTERNS:
            out = pattern.sub(f"{label}=[REDACTED]", out)
        return out
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_ns: int
    end_ns: int
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | error

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["attributes"] = redact(d.get("attributes", {}))
        return d


class Tracer:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._spans: list[Span] = []
        self._counter = 0

    def _next_span_id(self) -> str:
        self._counter += 1
        return f"s{self._counter:04d}"

    def start(
        self,
        name: str,
        *,
        parent: Span | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        s = Span(
            name=name,
            trace_id=self.trace_id,
            span_id=self._next_span_id(),
            parent_span_id=parent.span_id if parent else None,
            start_ns=_now_ns(),
            end_ns=0,
            attributes=attributes or {},
        )
        self._spans.append(s)
        return s

    def end(self, span: Span, *, status: str = "ok", extra: dict[str, Any] | None = None) -> None:
        span.end_ns = _now_ns()
        span.status = status
        if extra:
            span.attributes.update(extra)

    def export(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._spans]


def _now_ns() -> int:
    # time.time_ns() returns a true int (no float precision loss).
    # datetime.now(tz).timestamp() * 1e9 overflows float precision past 2^53.
    return time.time_ns()


def trace_to_jsonl(tracer: Tracer) -> str:
    """Serialise spans to redacted JSONL."""
    return "\n".join(json.dumps(s) for s in tracer.export())
