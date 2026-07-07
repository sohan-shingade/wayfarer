"""Optional FlightProvider backed by SerpApi's `google_flights` engine. Reliable
(an SLA, multi-seller links) but metered: the free tier is ~250 searches/mo shared
with the hotels engine. fli stays the default free flight source; swap to this in
cli.py if you want reliability over zero cost.

Field names verified live (see scripts/record_fixtures.py):
  best_flights[] / other_flights[] -> each has .price (round-trip party total) and
  .flights[] legs with departure_airport{id,time}, arrival_airport{id,time},
  airline, flight_number.

LIMITATION: a single google_flights round-trip call returns the OUTBOUND options
only; the matching return legs require a second call with a departure_token. To
stay within one call per finalist we record the outbound legs and the true
round-trip price, and fetch the return legs only in exact_round_trip via the token
when available. Coarse pruning just needs the price.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from ..config import SETTINGS
from ..models import ExactFlight, FlightLeg
from .base import CheapestRT
from .cache import get_cache
from .serpapi_client import serpapi_get

log = logging.getLogger(__name__)
_cache = get_cache(SETTINGS.provider_cache_ttl_s)


def _all_options(payload: dict) -> list[dict]:
    return (payload.get("best_flights") or []) + (payload.get("other_flights") or [])


def _leg(raw: dict) -> FlightLeg:
    dep, arr = raw.get("departure_airport") or {}, raw.get("arrival_airport") or {}
    return FlightLeg(
        carrier=raw.get("airline", ""),
        flight_number=raw.get("flight_number", ""),
        depart_airport=dep.get("id", ""),
        arrive_airport=arr.get("id", ""),
        depart_dt=dep.get("time", ""),
        arrive_dt=arr.get("time", ""),
    )


def _book_url(origin: str, dest: str, out_date: str, back_date: str) -> str:
    q = f"Flights from {origin} to {dest} on {out_date} through {back_date}"
    return "https://www.google.com/travel/flights?q=" + quote(q)


class SerpApiFlightProvider:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _params(self, origin, dest, out_date, back_date, pax) -> dict:
        return {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": dest,
            "outbound_date": out_date[:10],
            "return_date": back_date[:10],
            "adults": str(pax),
            "currency": "USD",
            "gl": "us",
            "hl": "en",
            "type": "1",  # round trip
            "api_key": self.api_key,
        }

    async def price_insights(self, *, origin, dest, out_date, back_date, pax) -> dict | None:
        """Cheapest fare + that route's typical price range (for deal detection).
        Returns {price, lowest_price, typical_low, typical_high, price_level} or None.
        Cached (JSON) so repeated deal scans of the same route are free within TTL.
        """
        key = f"serpapi:insights:{origin}:{dest}:{out_date}:{back_date}:{pax}"
        cached = _cache.get(key)
        if cached is None:
            data = await serpapi_get(self._params(origin, dest, out_date, back_date, pax))
            options = [o for o in _all_options(data) if isinstance(o.get("price"), (int, float))]
            pi = data.get("price_insights") or {}
            rng = pi.get("typical_price_range") or [None, None]
            cached = {
                "price": min((o["price"] for o in options), default=None),
                "lowest_price": pi.get("lowest_price"),
                "typical_low": rng[0] if len(rng) > 0 else None,
                "typical_high": rng[1] if len(rng) > 1 else None,
                "price_level": pi.get("price_level", ""),
            }
            _cache.set(key, cached)
        return cached if cached.get("price") is not None else None

    async def cheapest_in_month(self, *, origin, dest, month, nights, pax) -> CheapestRT | None:
        # google_flights has no month grid here; probe a mid-month departure as a
        # representative price for pruning (approximate is fine for the coarse pass).
        from datetime import datetime, timedelta

        year, mon = (int(x) for x in month.split("-"))
        out = f"{year:04d}-{mon:02d}-15"
        back = (datetime.strptime(out, "%Y-%m-%d") + timedelta(days=nights)).date().isoformat()
        data = await serpapi_get(self._params(origin, dest, out, back, pax))
        prices = [o["price"] for o in _all_options(data) if isinstance(o.get("price"), (int, float))]
        if not prices:
            return None
        return CheapestRT(price_total=round(float(min(prices)), 2), out_date=out, back_date=back)

    async def exact_round_trip(self, *, origin, dest, out_date, back_date, pax) -> ExactFlight | None:
        data = await serpapi_get(self._params(origin, dest, out_date, back_date, pax))
        options = [o for o in _all_options(data) if isinstance(o.get("price"), (int, float))]
        if not options:
            return None
        best = min(options, key=lambda o: o["price"])
        legs_out = [_leg(f) for f in best.get("flights", [])]
        legs_back: list[FlightLeg] = []
        token = best.get("departure_token")
        if token:
            try:
                ret = await serpapi_get({**self._params(origin, dest, out_date, back_date, pax),
                                         "departure_token": token})
                ret_best = min(
                    (o for o in _all_options(ret) if isinstance(o.get("price"), (int, float))),
                    key=lambda o: o["price"], default=None,
                )
                if ret_best:
                    seen = {(leg.flight_number, leg.depart_dt) for leg in legs_out}
                    legs_back = [_leg(f) for f in ret_best.get("flights", [])
                                 if (f.get("flight_number"),
                                     (f.get("departure_airport") or {}).get("time")) not in seen]
            except Exception:  # noqa: BLE001  return-leg lookup is best-effort
                log.debug("serpapi return-leg lookup failed", exc_info=True)
        return ExactFlight(
            legs_out=legs_out,
            legs_back=legs_back,
            price_total=round(float(best["price"]), 2),
            book_url=_book_url(origin, dest, out_date, back_date),
        )
