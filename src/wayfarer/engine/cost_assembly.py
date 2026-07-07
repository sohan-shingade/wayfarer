"""Stage 3: attach lodging + per-diem to each survivor and keep what fits $budget."""
from __future__ import annotations

import asyncio
import logging

from ..config import Settings
from ..models import Brief, CoarseQuote, PricedCandidate
from ..providers.base import HotelProvider, PriorsProvider
from ..text import place_query
from .budget import assemble_budget, fits

log = logging.getLogger(__name__)


async def assemble_costs(
    quotes: list[CoarseQuote],
    brief: Brief,
    hotels: HotelProvider,
    priors: PriorsProvider,
    settings: Settings,
) -> list[PricedCandidate]:
    async def price_one(q: CoarseQuote) -> PricedCandidate | None:
        try:
            nightly = await hotels.cheapest_nightly(
                q=place_query(q.candidate.city, q.candidate.country, q.candidate.region),
                check_in=q.out_date,
                check_out=q.back_date,
                pax=brief.pax,
            )
            tier = priors.cost_tier(q.candidate.city, q.candidate.country)
        except Exception:  # noqa: BLE001  (one dead candidate must not kill the run)
            log.debug("cost assembly failed for %s; dropping", q.candidate.city, exc_info=True)
            return None
        budget = assemble_budget(
            flights=q.cheapest_rt_total,
            nightly_rate=nightly,
            nights=brief.nights,
            per_diem_pp_per_day=settings.per_diem_by_tier[tier],
            pax=brief.pax,
            buffer_pct=settings.buffer_pct,
        )
        if not fits(budget, brief.budget_total, settings.budget_margin):
            return None
        return PricedCandidate(quote=q, budget=budget)

    priced = await asyncio.gather(*(price_one(q) for q in quotes))
    return [p for p in priced if p]
