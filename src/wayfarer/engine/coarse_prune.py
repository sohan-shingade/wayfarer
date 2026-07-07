"""Stage 2: one cheap flight call per candidate, drop the unaffordable ones.

This is the rate-limit chokepoint. Concurrency is bounded and every result is
cached by the provider layer. Do NOT let this fan out unbounded.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import Settings
from ..models import Brief, Candidate, CoarseQuote
from ..providers.base import FlightProvider

log = logging.getLogger(__name__)


async def coarse_prune(
    candidates: list[Candidate],
    brief: Brief,
    flights: FlightProvider,
    settings: Settings,
) -> list[CoarseQuote]:
    origins = brief.origins or [brief.origin_iata]
    # max_coarse_calls is a hard cap on PROVIDER CALLS, not candidates. With N
    # origins each candidate costs N calls, so shrink the candidate slice to keep
    # the total bounded by the cap.
    per_candidate = max(1, len(origins))
    candidates = candidates[: max(1, settings.max_coarse_calls // per_candidate)]
    sem = asyncio.Semaphore(settings.coarse_concurrency)

    async def quote_one(c: Candidate) -> CoarseQuote | None:
        async with sem:
            best = None
            best_origin = ""
            for origin in origins:
                try:
                    cheapest = await flights.cheapest_in_month(
                        origin=origin, dest=c.iata, month=brief.month,
                        nights=brief.nights, pax=brief.pax,
                    )
                except Exception:  # noqa: BLE001  one dead (origin,candidate) must not kill the run
                    log.debug("coarse flight quote failed for %s->%s; skipping",
                              origin, c.iata, exc_info=True)
                    continue
                if cheapest is None:
                    continue
                if best is None or cheapest.price_total < best.price_total:
                    best, best_origin = cheapest, origin
            if best is None:
                return None
            return CoarseQuote(
                candidate=c,
                cheapest_rt_total=best.price_total,
                out_date=best.out_date,
                back_date=best.back_date,
                origin=best_origin,
            )

    quotes = [q for q in await asyncio.gather(*(quote_one(c) for c in candidates)) if q]

    ceiling = brief.budget_total * settings.flight_share_ceiling
    survivors = [q for q in quotes if q.cheapest_rt_total <= ceiling]
    survivors.sort(key=lambda q: q.cheapest_rt_total)
    return survivors[: settings.coarse_survivors]
