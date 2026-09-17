"""OpenTelemetry exporter + redaction.

ADR-0011: `Tracer` wraps a real `opentelemetry-sdk` `Tracer` when one is
supplied AND the `otel` extra is installed; it falls back to the original
no-op bookkeeping recorder (a plain list of `Span` dataclasses) otherwise.
The public surface -- `start(name, parent=, attributes=)`,
`end(span, status=, extra=)`, `export()` -- is preserved byte-compatibly
either way; `tests/test_observability.py` is the regression lock for the
fallback path, which is what runs whenever the `otel` extra isn't
installed or no `otel_tracer` is passed in.

Per the proposal:
  - OpenTelemetry only (no LangSmith)
  - Spans around model calls, tool calls, state transitions, failures
  - Redact api_key, authorization, bearer, and known credential fields
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export import SpanExporter
    from opentelemetry.trace import Tracer as _OtelSdkTracer

REDACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # key=value forms
    ("api_key", re.compile(r"(?i)(api[_-]?key)\s*[:=]\s*[^\s,;}]+")),
    # Bearer / Authorization: Bearer <token> -- MUST run before `authorization`.
    # `authorization`'s value class ([^\s,;}]+) stops at the first space, so
    # on "Authorization: Bearer <token>" it would consume only the literal
    # word "Bearer" and leave <token> untouched. Redacting `bearer` first
    # strips the whole "Bearer <token>" run; `authorization` then only
    # relabels what's left (ADR-0011 §Context item 1).
    ("bearer", re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._\-]+")),
    ("authorization", re.compile(r"(?i)(authorization)\s*[:=]\s*[^\s,;}]+")),
    ("password", re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*[^\s,;}]+")),
    ("token", re.compile(r"(?i)(token)\s*[:=]\s*[^\s,;}]+")),
    ("secret", re.compile(r"(?i)(secret)\s*[:=]\s*[^\s,;}]+")),
    # JWT-shape tokens (header.payload.signature)
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")),
    # sk-cp-... and sk-... keys (any non-trivial length)
    ("secret_key", re.compile(r"sk-(?:cp-)?[A-Za-z0-9_-]{4,}")),
    # Bare gh[pousr]_... GitHub token shape, not preceded by a `token=` key
    # (that case is already covered by the `token` pattern above).
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}")),
    # Connection-string userinfo: scheme://user:password@ -- covers
    # postgresql://user:pass@host/db and similar DSNs (ADR-0011 §Context
    # item 2; literal example at docker/docker-compose.yml).
    ("dsn", re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@]+@")),
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


def _otel_safe_attrs(attributes: dict[str, Any]) -> dict[str, Any]:
    """Coerce attribute values into shapes the OTel SDK accepts (str, bool,
    int, float, or a homogeneous sequence of those). Anything else -- None,
    a nested dict, a mixed list -- is stringified rather than dropped, so a
    caller passing an unexpected value still gets *something* in the span
    instead of a silent `set_attribute` failure."""
    out: dict[str, Any] = {}
    for k, v in attributes.items():
        if v is None:
            continue
        if isinstance(v, (str, bool, int, float)):
            out[k] = v
        elif isinstance(v, (list, tuple)) and all(isinstance(x, (str, bool, int, float)) for x in v):
            out[k] = list(v)
        else:
            out[k] = str(v)
    return out


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
    """Byte-compatible with the original no-op recorder; optionally backed
    by a real `opentelemetry.trace.Tracer` (ADR-0011 §Decision 3).

    `otel_tracer` is normally obtained from a `TracerProvider` built in
    `api/server.py::_lifespan` (`provider.get_tracer(...)`) and passed in
    per-request. When it's `None` -- the default, and the only option when
    the `otel` extra isn't installed -- this class behaves exactly as it
    did before this ADR: an in-memory list of `Span` dataclasses, nothing
    exported anywhere.
    """

    def __init__(self, trace_id: str, *, otel_tracer: _OtelSdkTracer | None = None) -> None:
        self.trace_id = trace_id
        self._spans: list[Span] = []
        self._counter = 0
        self._otel_tracer = otel_tracer
        self._open_stack: list[Span] = []
        self._otel_spans: dict[str, Any] = {}

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
        # Semantic change from the pre-ADR-0011 Tracer: with no explicit
        # `parent`, attach to the innermost still-open span instead of
        # always becoming a root. This is what makes `wiki.search` and
        # `wiki.qa.llm_chat` children of the API-layer root without either
        # node passing `parent=` explicitly.
        effective_parent = parent if parent is not None else (
            self._open_stack[-1] if self._open_stack else None
        )
        s = Span(
            name=name,
            trace_id=self.trace_id,
            span_id=self._next_span_id(),
            parent_span_id=effective_parent.span_id if effective_parent else None,
            start_ns=_now_ns(),
            end_ns=0,
            attributes=dict(attributes or {}),
        )
        self._spans.append(s)
        self._open_stack.append(s)
        if self._otel_tracer is not None:
            otel_context = None
            if effective_parent is not None:
                parent_otel_span = self._otel_spans.get(effective_parent.span_id)
                if parent_otel_span is not None:
                    from opentelemetry import trace as otel_trace_api

                    otel_context = otel_trace_api.set_span_in_context(parent_otel_span)
            otel_span = self._otel_tracer.start_span(
                name, context=otel_context, attributes=_otel_safe_attrs(attributes or {})
            )
            self._otel_spans[s.span_id] = otel_span
        return s

    def end(self, span: Span, *, status: str = "ok", extra: dict[str, Any] | None = None) -> None:
        span.end_ns = _now_ns()
        span.status = status
        if extra:
            span.attributes.update(extra)
        if self._open_stack and self._open_stack[-1] is span:
            self._open_stack.pop()
        elif span in self._open_stack:
            self._open_stack.remove(span)
        otel_span = self._otel_spans.pop(span.span_id, None)
        if otel_span is not None:
            if extra:
                for k, v in _otel_safe_attrs(extra).items():
                    otel_span.set_attribute(k, v)
            if status == "error":
                from opentelemetry.trace import Status, StatusCode

                otel_span.set_status(Status(StatusCode.ERROR))
            otel_span.end()

    def export(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._spans]


def _now_ns() -> int:
    # time.time_ns() returns a true int (no float precision loss).
    # datetime.now(tz).timestamp() * 1e9 overflows float precision past 2^53.
    return time.time_ns()


def trace_to_jsonl(tracer: Tracer) -> str:
    """Serialise spans to redacted JSONL."""
    return "\n".join(json.dumps(s) for s in tracer.export())


class RedactingSpanExporter:
    """Decorator applying `redact()` to span attributes, event attributes,
    and `status.description` before delegating to the wrapped exporter
    (ADR-0011 §Decision 4). The exporter boundary is the only chokepoint
    that also covers spans not created by our own `Tracer`.

    `ReadableSpan` has no public "replace attributes" API; mutating the
    private `_attributes`/`_status` fields on the SDK-owned span object
    before handing it to the delegate is the accepted pattern other
    redacting-exporter implementations use, since these spans are
    exporter-owned regular Python objects, not frozen.
    """

    def __init__(self, delegate: SpanExporter) -> None:
        self._delegate = delegate

    def export(self, spans):  # noqa: ANN001, ANN201 - shape comes from opentelemetry-sdk
        from opentelemetry.trace.status import Status

        for span in spans:
            if span.attributes:
                span._attributes = redact(dict(span.attributes))  # noqa: SLF001
            for event in getattr(span, "events", None) or ():
                if event.attributes:
                    event._attributes = redact(dict(event.attributes))  # noqa: SLF001
            status = span.status
            if status is not None and status.description:
                span._status = Status(status.status_code, redact(status.description))  # noqa: SLF001
        return self._delegate.export(spans)

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        force_flush = getattr(self._delegate, "force_flush", None)
        return force_flush(timeout_millis) if force_flush else True


class JsonlFileSpanExporter:
    """Writes `{runs_dir}/{trace_id}.jsonl`, one redacted span per line --
    `trace_to_jsonl`'s existing shape, now fed by real SDK spans instead of
    the bookkeeping `Span` dataclass. Dependency-free: no `opentelemetry-*`
    import at module scope, only inside `export()` for `SpanExportResult`,
    so importing this module never requires the `otel` extra."""

    def __init__(self, runs_dir: str | Path) -> None:
        self._runs_dir = Path(runs_dir)

    def export(self, spans):  # noqa: ANN001, ANN201 - shape comes from opentelemetry-sdk
        from opentelemetry.sdk.trace.export import SpanExportResult

        self._runs_dir.mkdir(parents=True, exist_ok=True)
        by_trace: dict[str, list[dict[str, Any]]] = {}
        for span in spans:
            ctx = span.get_span_context()
            trace_id_hex = format(ctx.trace_id, "032x")
            span_id_hex = format(ctx.span_id, "016x")
            parent_id_hex = format(span.parent.span_id, "016x") if span.parent else None
            is_error = span.status is not None and span.status.status_code.name == "ERROR"
            by_trace.setdefault(trace_id_hex, []).append(
                {
                    "name": span.name,
                    "trace_id": trace_id_hex,
                    "span_id": span_id_hex,
                    "parent_span_id": parent_id_hex,
                    "start_ns": span.start_time,
                    "end_ns": span.end_time,
                    "attributes": dict(span.attributes or {}),
                    "status": "error" if is_error else "ok",
                }
            )
        for trace_id_hex, records in by_trace.items():
            path = self._runs_dir / f"{trace_id_hex}.jsonl"
            with path.open("a", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:  # noqa: ARG002
        return True
