"""Stage 3b: rank priced candidates and keep the top N for full plan writing.

Score blends budget headroom, vibe fit, and in-season quality. Tune the weights.
"""
from __future__ import annotations

from ..config import Settings
from ..models import Brief, PricedCandidate


def rank(priced: list[PricedCandidate], brief: Brief, settings: Settings) -> list[PricedCandidate]:
    for p in priced:
        headroom = max(0.0, (brief.budget_total - p.budget.total) / brief.budget_total)
        vibe = p.quote.candidate.vibe_score
        season = 1.0 if p.quote.candidate.in_season else 0.3
        p.rank_score = round(0.45 * vibe + 0.35 * headroom + 0.20 * season, 4)
    priced.sort(key=lambda p: p.rank_score, reverse=True)
    return priced[: settings.final_plans]
