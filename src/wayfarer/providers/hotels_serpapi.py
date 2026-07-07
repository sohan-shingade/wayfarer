"""HotelProvider backed by SerpApi's `google_hotels` engine (live Google Hotels
data, free tier ~250 searches/mo, same key as the flights engine).

Field names verified against a live call (see scripts/record_fixtures.py):
  properties[].rate_per_night.extracted_lowest   -> nightly rate (number)
  properties[].total_rate.extracted_lowest       -> stay total (number)
  properties[].name / .link                      -> name + book-out link

Parsing is pure (`parse_cheapest_nightly`, `parse_exact`) so the fast-tier tests
feed a recorded payload through the same code the live path uses. No IATA->city
mapping: the engine passes a free-text location `q` (e.g. "Reykjavik, Iceland").
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from ..config import SETTINGS
from ..models import ExactHotel
from .cache import get_cache
from .serpapi_client import serpapi_get

log = logging.getLogger(__name__)
_cache = get_cache(SETTINGS.provider_cache_ttl_s)


def _nights(check_in: str, check_out: str) -> int:
    a = datetime.strptime(check_in[:10], "%Y-%m-%d")
    b = datetime.strptime(check_out[:10], "%Y-%m-%d")
    return max(1, (b - a).days)


def _nightly(prop: dict) -> float | None:
    rate = (prop.get("rate_per_night") or {}).get("extracted_lowest")
    return float(rate) if isinstance(rate, (int, float)) else None


def parse_cheapest_nightly(payload: dict) -> float:
    rates = [r for p in (payload.get("properties") or []) if (r := _nightly(p)) is not None]
    if not rates:
        raise ValueError("no nightly rates in serpapi google_hotels payload")
    return round(min(rates), 2)


def parse_exact(payload: dict, nights: int) -> ExactHotel | None:
    best: dict | None = None
    best_rate: float | None = None
    for prop in payload.get("properties") or []:
        rate = _nightly(prop)
        if rate is None:
            continue
        if best_rate is None or rate < best_rate:
            best_rate, best = rate, prop
    if best is None or best_rate is None:
        return None
    total = (best.get("total_rate") or {}).get("extracted_lowest")
    total = round(float(total), 2) if isinstance(total, (int, float)) else round(best_rate * nights, 2)
    gps = best.get("gps_coordinates") or {}
    lat = gps.get("latitude")
    lng = gps.get("longitude")
    return ExactHotel(
        name=best.get("name", "(unnamed)"),
        nightly_rate=round(best_rate, 2),
        nights=nights,
        total=total,
        book_url=best.get("link") or best.get("serpapi_property_details_link") or "",
        lat=float(lat) if isinstance(lat, (int, float)) else None,
        lng=float(lng) if isinstance(lng, (int, float)) else None,
    )


class SerpApiHotelProvider:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("SERPAPI_API_KEY", "")
        if not self.api_key:
            raise ValueError("SERPAPI_API_KEY required for SerpApiHotelProvider")

    async def _search(self, q: str, check_in: str, check_out: str, pax: int) -> dict:
        key = f"hotels:{q}:{check_in}:{check_out}:{pax}"
        if (cached := _cache.get(key)) is not None:
            return cached
        data = await serpapi_get({
            "engine": "google_hotels",
            "q": q,
            "check_in_date": check_in[:10],
            "check_out_date": check_out[:10],
            "adults": str(pax),
            "currency": "USD",
            "gl": "us",
            "hl": "en",
            "api_key": self.api_key,
        })
        _cache.set(key, data)
        return data

    async def cheapest_nightly(self, *, q: str, check_in: str, check_out: str, pax: int) -> float:
        return parse_cheapest_nightly(await self._search(q, check_in, check_out, pax))

    async def exact_hotel(
        self, *, q: str, check_in: str, check_out: str, pax: int
    ) -> ExactHotel | None:
        data = await self._search(q, check_in, check_out, pax)
        return parse_exact(data, _nights(check_in, check_out))
