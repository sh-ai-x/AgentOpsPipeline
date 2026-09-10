"""Per-model token pricing (USD per 1M tokens).

Used by the OpenAI-compat and MiniMax adapters to populate
`Usage.cost_usd` from the API-reported `usage.prompt_tokens` /
`usage.completion_tokens`. The provider APIs don't currently return
cost directly, so we compute it locally.

Pricing values are approximate; override via the `MODEL_PRICING` dict or
`AGENTOPS_PRICING_JSON` env var (a JSON object keyed by model name
mapping to {"input_per_1m": float, "output_per_1m": float}).

Default rates (USD per 1M tokens) are rough placeholders for cheap
small models -- edit as the provider publishes real numbers.
"""
from __future__ import annotations

import json
import os
from typing import TypedDict


class ModelRate(TypedDict):
    input_per_1m: float
    output_per_1m: float


# Placeholder rates. Replace with the provider's published pricing.
DEFAULT_PRICING: dict[str, ModelRate] = {
    "MiniMax-M3": {"input_per_1m": 0.50, "output_per_1m": 1.50},
    "minimax-M3": {"input_per_1m": 0.50, "output_per_1m": 1.50},
    "local-fake-v1": {"input_per_1m": 0.0, "output_per_1m": 0.0},
}


def _load_env_pricing() -> dict[str, ModelRate]:
    """Allow runtime overrides via AGENTOPS_PRICING_JSON (one-off JSON dict)."""
    raw = os.environ.get("AGENTOPS_PRICING_JSON", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {k: {"input_per_1m": float(v["input_per_1m"]), "output_per_1m": float(v["output_per_1m"])} for k, v in data.items()}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {}


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return cost (USD) for the given token counts, using per-model rates."""
    rates = {**_load_env_pricing(), **DEFAULT_PRICING}
    rate = rates.get(model) or rates.get("MiniMax-M3")  # safe default
    return (
        prompt_tokens / 1_000_000.0 * rate["input_per_1m"]
        + completion_tokens / 1_000_000.0 * rate["output_per_1m"]
    )
