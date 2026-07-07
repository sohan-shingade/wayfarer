"""Cheap-flight / deal detection. Two pure functions, no I/O:

- `tag_deals`: RELATIVE, free. Within a single run's coarse quotes, flag the
  standout-cheap ones (well below the median). Marks `CoarseQuote.is_deal`.
- `score_deal`: ABSOLUTE. Given a fare + that route's typical price range (from
  SerpApi price_insights), decide if it's a genuine deal vs history and by how
  much. Used by deal-hunt mode.
"""
from __future__ import annotations

from ..models import CoarseQuote


def tag_deals(quotes: list[CoarseQuote], ratio: float = 0.65, min_n: int = 3) -> list[CoarseQuote]:
    """Flag quotes whose fare is <= ratio * median fare of the set. No-op below
    min_n quotes (median is meaningless on a tiny sample)."""
    if len(quotes) < min_n:
        return quotes
    prices = sorted(q.cheapest_rt_total for q in quotes)
    median = prices[len(prices) // 2]
    if median <= 0:
        return quotes
    for q in quotes:
        q.is_deal = q.cheapest_rt_total <= ratio * median
    return quotes


def score_deal(
    price: float,
    typical_low: float | None,
    typical_high: float | None,
    price_level: str = "",
) -> dict:
    """Absolute deal verdict for one route.

    A fare is a deal when it lands below the bottom of the typical range, or Google
    explicitly calls the level "low". `discount_pct` is how far below the typical
    low the fare is (0 if not below it), so callers can rank the best deals first.
    """
    is_low_level = (price_level or "").lower() == "low"
    below_typical = typical_low is not None and price < typical_low
    discount_pct = 0.0
    if typical_low and price < typical_low:
        discount_pct = round((typical_low - price) / typical_low * 100, 1)
    return {
        "is_deal": bool(below_typical or is_low_level),
        "discount_pct": discount_pct,
        "price": round(float(price), 2),
        "typical_low": typical_low,
        "typical_high": typical_high,
        "price_level": price_level,
    }
