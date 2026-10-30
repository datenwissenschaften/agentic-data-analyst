"""Token use and cost of the Claude calls behind one answer."""

from dataclasses import dataclass

from anthropic.types.beta import BetaUsage

# USD per million tokens: input, output, cache write (5 min), cache read. Claude API list prices as of 2026-09-25.
# The fallback models are listed because a safety decline may be answered by them instead (agent.py, `fallbacks`).
PRICES_PER_MILLION = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 6.25, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    # Responses may name the dated snapshot instead of the alias.
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    "claude-haiku-4-5-20251001": (1.00, 5.00, 1.25, 0.10),
}


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    # None when a model without a known price answered; the token counts are still exact.
    cost_usd: float | None = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        cost = None if self.cost_usd is None or other.cost_usd is None else self.cost_usd + other.cost_usd
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cost_usd=cost,
        )


def usage_of(model: str, usage: BetaUsage) -> Usage:
    """Usage of one API response. `input_tokens` excludes cached tokens, which are priced separately."""
    counts = (usage.input_tokens, usage.output_tokens, usage.cache_creation_input_tokens or 0, usage.cache_read_input_tokens or 0)
    prices = PRICES_PER_MILLION.get(model)
    cost = None if prices is None else sum(count * price for count, price in zip(counts, prices, strict=True)) / 1_000_000
    return Usage(*counts, cost_usd=cost)


def format_usage(answer: Usage, session: Usage) -> str:
    input_tokens = answer.input_tokens + answer.cache_write_tokens + answer.cache_read_tokens
    return (
        f"Tokens: {input_tokens:,} in ({answer.cache_read_tokens:,} cached) · {answer.output_tokens:,} out · "
        f"cost {_dollars(answer.cost_usd)} · session total {_dollars(session.cost_usd)}"
    )


def _dollars(cost: float | None) -> str:
    return "unknown" if cost is None else f"${cost:.4f}"
