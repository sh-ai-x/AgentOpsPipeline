"""Per-model token pricing (USD per 1M tokens).

Used by the OpenAI-compat and MiniMax adapters to populate
`Usage.cost_usd` from the API-reported `usage.prompt_tokens` /
`usage.completion_tokens`. The provider APIs don't currently return
cost directly, so we compute it locally.

Pricing values are approximate; override via the `DEFAULT_PRICING` dict
or `AGENTOPS_PRICING_JSON` env var (a JSON object keyed by model name
mapping to {"input_per_1m": float, "output_per_1m": float}).

Default rates (USD per 1M tokens) are rough placeholders for cheap
small models -- edit as the provider publishes real numbers.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import TypedDict


log = logging.getLogger(__name__)


class ModelRate(TypedDict):
    input_per_1m: float
    output_per_1m: float


# Placeholder rates. Replace with the provider's published pricing.
# env-loaded overrides (AGENTOPS_PRICING_JSON) are merged AT IMPORT TIME
# so env-wins semantics are correct and the chat hot path stays cheap.
DEFAULT_PRICING: dict[str, ModelRate] = {
    "MiniMax-M3": {"input_per_1m": 0.50, "output_per_1m": 1.50},
    "local-fake-v1": {"input_per_1m": 0.0, "output_per_1m": 0.0},
}


@lru_cache(maxsize=1)
def _env_pricing_overrides() -> dict[str, ModelRate]:
    """Parse AGENTOPS_PRICING_JSON once at module import. Env wins."""
    raw = os.environ.get("AGENTOPS_PRICING_JSON", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        out: dict[str, ModelRate] = {}
        for k, v in data.items():
            out[k] = {
                "input_per_1m": float(v["input_per_1m"]),
                "output_per_1m": float(v["output_per_1m"]),
            }
        return out
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        log.warning("AGENTOPS_PRICING_JSON is not valid JSON; ignoring")
        return {}


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return cost (USD). Unknown models return 0.0 (no fabricated billing)."""
    # Env wins, then DEFAULT_PRICING. lru_cache makes the dict lookup O(1)
    # on the chat hot path.
    overrides = _env_pricing_overrides()
    rate = overrides.get(model) or DEFAULT_PRICING.get(model)
    if rate is None:
        return 0.0
    return (
        prompt_tokens / 1_000_000.0 * rate["input_per_1m"]
        + completion_tokens / 1_000_000.0 * rate["output_per_1m"]
    )
