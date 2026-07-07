"""The orchestrator: a deterministic state machine, NOT an LLM loop. It sequences
the stages, enforces caps, and calls LLM agents only at the four labeled points
(parse, brainstorm, write, critique). Everything between is plain code.

Pipeline:
  prompt -> parse_brief -> [elicitation gate] -> brainstorm
         -> coarse_prune (fli) -> assemble_costs (+hotels +priors) -> rank
         -> exact_pricing -> write_itinerary -> critique -> plans
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from .agents import llm_agents as agents
from .agents.runtime import AgentRuntime
from .config import Settings
from .engine.budget import rebudget_from_exact
from .engine.coarse_prune import coarse_prune
from .engine.cost_assembly import assemble_costs
from .engine.deals import tag_deals
from .engine.rank import rank
from .models import Brief, ExactFlight, ExactHotel, Plan
from .providers.base import FlightProvider, HotelProvider, PriorsProvider
from .text import google_flights_url, hotel_booking_url, place_query

log = logging.getLogger(__name__)


# An elicitation hook: given a partial brief dict, return the answers needed to
# complete it (origin, long-haul-ok, hard-ceiling). The CLI wires this to stdin;
# a web frontend would wire it to the two-question UI. Returns the patched dict.
ElicitFn = Callable[[dict], dict]


class Orchestrator:
    def __init__(
        self,
        runtime: AgentRuntime,
        flights: FlightProvider,
        hotels: HotelProvider,
        priors: PriorsProvider,
        settings: Settings,
        elicit: ElicitFn,
    ) -> None:
        self.rt = runtime
        self.flights = flights
        self.hotels = hotels
        self.priors = priors
        self.s = settings
        self.elicit = elicit

    async def plan_trip(self, request: str, overrides: dict | None = None) -> list[Plan]:
        plans, _ = await self.plan_trip_with_brief(request, overrides)
        return plans

    async def plan_trip_with_brief(
        self, request: str, overrides: dict | None = None
    ) -> tuple[list[Plan], Brief]:
        # Stage 0: parse + elicitation gate (cheap, before any spend)
        raw = await agents.parse_brief(self.rt, request, self.s.model_brief)
        if overrides:  # CLI flags win over the LLM's parse
            raw.update({k: v for k, v in overrides.items() if v is not None})
        if not raw.get("origin_iata") or raw.get("long_haul_ok") is None:
            raw = self.elicit(raw)
        brief = Brief(**raw)
        if not brief.origins:
            brief.origins = [brief.origin_iata]

        # Stage 1: brainstorm candidates (no API calls). Only price as many as the
        # coarse cap allows across the origins, so we don't pay to generate
        # candidates that the rate-limited coarse pass will never reach.
        n_candidates = min(self.s.max_candidates,
                           max(8, self.s.max_coarse_calls // max(1, len(brief.origins))))
        candidates = await agents.brainstorm(self.rt, brief, n_candidates)

        # Stage 2: coarse flight prune (the rate-limit chokepoint)
        quotes = await coarse_prune(candidates, brief, self.flights, self.s)
        if not quotes:
            return [], brief
        tag_deals(quotes, self.s.deal_ratio)  # flag standout-cheap fares (free, relative)

        # Stage 3: assemble full budgets, drop what doesn't fit, rank, keep top N
        priced = await assemble_costs(quotes, brief, self.hotels, self.priors, self.s)
        finalists = rank(priced, brief, self.s)

        # Stage 4: exact pricing + itinerary + critic, finalists only. A finalist
        # whose exact pricing dies (fli is flaky) is dropped, not allowed to kill
        # the whole run.
        plans = await asyncio.gather(*(self._finalize(brief, p) for p in finalists))
        return [p for p in plans if p is not None], brief

    async def _finalize(self, brief: Brief, priced) -> Plan | None:
        c = priced.quote.candidate
        origin = priced.quote.origin or brief.origin_iata
        try:
            flight = await self.flights.exact_round_trip(
                origin=origin, dest=c.iata,
                out_date=priced.quote.out_date, back_date=priced.quote.back_date, pax=brief.pax,
            )
        except Exception:  # noqa: BLE001  fli exact search is unreliable
            log.debug("exact flight pricing failed for %s; using coarse price", c.iata, exc_info=True)
            flight = None
        if flight is None:
            # Fall back to the coarse round-trip total so the finalist still produces
            # a plan with a real (if less precise) flight figure. No legs, but still
            # give a working Google Flights deep link for the dates so it's bookable.
            flight = ExactFlight(
                legs_out=[], legs_back=[],
                price_total=priced.quote.cheapest_rt_total,
                book_url=google_flights_url(
                    origin, c.iata, priced.quote.out_date, priced.quote.back_date,
                    brief.pax,
                ),
            )
        loc = place_query(c.city, c.country, c.region)
        try:
            hotel = await self.hotels.exact_hotel(
                q=loc, check_in=priced.quote.out_date,
                check_out=priced.quote.back_date, pax=brief.pax,
            )
        except Exception:  # noqa: BLE001
            log.debug("exact hotel lookup failed for %s; trying coarse fallback", c.city, exc_info=True)
            hotel = None
        if hotel is None:
            # The finalist already passed budget assembly, so a coarse nightly rate
            # exists for it (cached). Synthesize a labeled estimate rather than drop
            # a viable destination when the exact-property lookup comes back empty.
            try:
                nightly = await self.hotels.cheapest_nightly(
                    q=loc, check_in=priced.quote.out_date,
                    check_out=priced.quote.back_date, pax=brief.pax,
                )
            except Exception:  # noqa: BLE001
                log.debug("coarse hotel fallback failed for %s; dropping finalist", c.city, exc_info=True)
                return None
            hotel = ExactHotel(
                name=f"(estimate) typical {c.city} hotel",
                nightly_rate=round(nightly, 2), nights=brief.nights,
                total=round(nightly * brief.nights, 2), book_url="",
            )
        # Hotel link: prefer the provider's own booking_url — trvl already returns a
        # dated, occupancy-aware deep link (e.g. trivago `...;dr-<in>-<out>;rc-1-<pax>`)
        # that lands on the exact property with real availability. Only synthesize a
        # search link when the provider gave none (e.g. flat-rate estimate).
        if not (hotel.book_url or "").strip():
            is_estimate = hotel.name.startswith("(estimate)")
            hotel.book_url = hotel_booking_url(
                "" if is_estimate else hotel.name, loc,
                priced.quote.out_date, priced.quote.back_date, brief.pax,
            )
        # Budget-truth: recompute the presented budget from the EXACT flight + hotel
        # the plan actually ships (keep the tier-based per-diem from assembly), so
        # the totals reconcile with the line items instead of the coarse estimate.
        budget = rebudget_from_exact(
            flight_total=flight.price_total,
            hotel_total=hotel.total,
            per_diem=priced.budget.per_diem,
            buffer_pct=self.s.buffer_pct,
        )
        summary, itinerary = await agents.write_itinerary(
            self.rt, brief, priced,
            flight.model_dump_json(), hotel.model_dump_json(), self.s.model_writer,
        )
        plan = Plan(
            destination=f"{c.city}, {c.country}",
            flight=flight, hotel=hotel, budget=budget,
            itinerary=itinerary, summary=summary,
            origin=origin, out_date=priced.quote.out_date, back_date=priced.quote.back_date,
            is_deal=priced.quote.is_deal,
        )
        verdict = await agents.critique(self.rt, brief, plan, self.s.model_critic)
        plan.status = verdict.get("status", "ok")
        plan.critic_notes = verdict.get("critic_notes", "")
        return plan
