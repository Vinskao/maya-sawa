"""Rough dollar cost of a scheduled routine's tokens.

The cloud transcript carries token counts but no price, and the usage database only prices GPT models. So the rate is
inferred from the dashboard's own recorded Claude Code costs (ccusage / OpenTelemetry) per model: input $/M tokens, with the
usual multipliers (output 5x, cache write 1.25x, cache read 0.1x). It is an estimate, labelled as one on the chart.
"""
INPUT_RATE_PER_MILLION = {
    "claude-opus-5-5": 1.46,    # 4 recorded days: $37.25
    "claude-sonnet-5-5": 1.18,  # 15 recorded days: $309.28
    "claude-sonnet-5": 1.05,
    "claude-opus-5": 2.64,
    "claude-haiku-4-5": 1.15,
}
DEFAULT_RATE = 1.2  # a model not listed yet: the Sonnet 5.5 rate, never zero, so the line does not silently drop a routine


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_creation: int = 0, cache_read: int = 0) -> float:
    rate = next((value for name, value in INPUT_RATE_PER_MILLION.items() if model.startswith(name)), DEFAULT_RATE)
    weighted = input_tokens + 5 * output_tokens + 1.25 * cache_creation + 0.1 * cache_read
    return round(rate * weighted / 1_000_000, 6)
