"""Fast tier: drive the real engine + orchestrator end-to-end with NO network and
NO claude. Provider responses are the RECORDED fixtures (genuine fli + SerpApi
data); the LLM agents are a scripted test double (the LLM is not a data provider).

This proves the deterministic spine (coarse prune -> cost assembly -> rank ->
exact pricing -> plan assembly) wires together and produces finished, in-budget,
status-set plans.
"""
import json

import pytest

from wayfarer.agents.runtime import AgentResult, AgentRuntime
from wayfarer.config import Settings
from wayfarer.orchestrator import Orchestrator
from wayfarer.providers.flights_fli import parse_cheapest_rt, parse_exact_rt
from wayfarer.providers.hotels_serpapi import parse_cheapest_nightly, parse_exact
from wayfarer.providers.priors import StaticPriors

_CANDIDATES = [
    {"city": "Reykjavik", "country": "Iceland", "iata": "KEF", "vibe_score": 0.95, "in_season": True, "rationale": "glaciers, waterfalls"},
    {"city": "Queenstown", "country": "New Zealand", "iata": "ZQN", "vibe_score": 0.90, "in_season": False, "rationale": "alpine"},
    {"city": "Bergen", "country": "Norway", "iata": "BGO", "vibe_score": 0.88, "in_season": True, "rationale": "fjords"},
    {"city": "Interlaken", "country": "Switzerland", "iata": "ZRH", "vibe_score": 0.85, "in_season": True, "rationale": "Alps"},
    {"city": "Cusco", "country": "Peru", "iata": "CUZ", "vibe_score": 0.80, "in_season": True, "rationale": "Andes"},
    {"city": "Banff", "country": "Canada", "iata": "YYC", "vibe_score": 0.78, "in_season": True, "rationale": "Rockies"},
]

_BRIEF = {
    "pax": 2, "budget_total": 6000, "origin_iata": "SFO", "month": "2026-08",
    "nights": 7, "flexible_dates": True, "vibe": ["dramatic landscapes"],
    "long_haul_ok": True, "hard_ceiling": True,
}

_ITINERARY = {
    "summary": "Seven days of glaciers, waterfalls and black-sand coast.",
    "itinerary": [{"day": d, "title": f"Day {d}", "notes": "landscapes"} for d in range(1, 8)],
}


class ReplayRuntime(AgentRuntime):
    """Scripted LLM: routes by each prompt template's distinctive opening line."""

    def __init__(self, brief, candidates):
        self._brief = brief
        self._candidates = candidates

    async def run(self, prompt: str, *, system=None) -> AgentResult:
        if "You convert a casual vacation request" in prompt:
            text = json.dumps(self._brief)
        elif "You are a destination scout" in prompt:
            text = json.dumps(self._candidates)
        elif "You write one tight day-by-day" in prompt:
            text = json.dumps(_ITINERARY)
        elif "You are a strict reviewer" in prompt:
            text = json.dumps({"status": "ok", "critic_notes": "sums under ceiling"})
        else:
            raise AssertionError(f"unexpected agent prompt: {prompt[:80]!r}")
        return AgentResult(text=text, raw={}, cost_usd=0.0, session_id="test")


class ReplayFlights:
    def __init__(self, dates_rows, exact_recs):
        self._dates, self._exact = dates_rows, exact_recs

    async def cheapest_in_month(self, *, origin, dest, month, nights, pax):
        return parse_cheapest_rt(self._dates)

    async def exact_round_trip(self, *, origin, dest, out_date, back_date, pax):
        return parse_exact_rt(self._exact, origin=origin, dest=dest,
                              out_date=out_date, back_date=back_date)


class ReplayHotels:
    def __init__(self, payload):
        self._payload = payload

    async def cheapest_nightly(self, *, q, check_in, check_out, pax):
        return parse_cheapest_nightly(self._payload)

    async def exact_hotel(self, *, q, check_in, check_out, pax):
        return parse_exact(self._payload, 7)


@pytest.mark.asyncio
async def test_pipeline_produces_plans(fli_dates, fli_exact, serpapi_hotels):
    orch = Orchestrator(
        runtime=ReplayRuntime(_BRIEF, _CANDIDATES),
        flights=ReplayFlights(fli_dates, fli_exact),
        hotels=ReplayHotels(serpapi_hotels),
        priors=StaticPriors(),
        settings=Settings(),
        elicit=lambda raw: raw,  # brief is complete; never invoked
    )
    plans = await orch.plan_trip("2 people, ~6k, august, insane landscapes, 4-5 options")

    assert 4 <= len(plans) <= 5, f"expected 4-5 plans, got {len(plans)}"
    for p in plans:
        assert p.destination
        assert p.budget.total <= _BRIEF["budget_total"]
        assert p.itinerary, "itinerary must be non-empty"
        assert p.flight.legs_out and p.flight.price_total > 0
        assert p.hotel.nightly_rate > 0
        assert p.status in ("ok", "over_budget", "flagged")
