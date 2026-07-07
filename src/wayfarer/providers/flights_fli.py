"""FlightProvider backed by `fli` (Google Flights, free, fragile, unofficial).

`fli` is the pip package `flights`. The real symbols (verified against the
installed version) are `fli.search.{SearchDates,SearchFlights}` and
`fli.models.{DateSearchFilters,FlightSearchFilters,FlightSegment,PassengerInfo,
Airport,SeatType,MaxStops,TripType,SortBy}`.

Two facts learned from probing the live API (see scripts/record_fixtures.py):
  * Round-trip `SearchFlights().search(...)` returns a list of
    ``(outbound_result, return_result)`` tuples; BOTH carry ``.price`` equal to the
    full round-trip total *for the whole party* (adults=pax). So we do NOT multiply
    by pax, and we read the price once.
  * Round-trip `SearchDates().search(...)` returns ``DatePrice`` rows whose
    ``.date`` is ``(out_dt, back_dt)`` and whose ``.price`` is likewise the party
    round-trip total.

Parsing is split out into pure functions (`parse_cheapest_rt`, `parse_exact_rt`)
that consume plain normalized dict rows, so the fast-tier tests can feed recorded
fixtures through the exact same code path the live calls use. Keep everything fli
inside this file: the engine must not learn fli exists.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import time
from datetime import datetime, timedelta

from ..config import SETTINGS
from ..models import ExactFlight, FlightLeg
from ..text import google_flights_url
from .base import CheapestRT
from .cache import get_cache

log = logging.getLogger(__name__)
_cache = get_cache(SETTINGS.provider_cache_ttl_s)

# fli is unofficial and rate-limited; retry transient failures with backoff.
_RETRIES = 3
_BACKOFF_BASE_S = 2.0


# ----------------------------- pure helpers --------------------------------- #
def _month_window(month: str, nights: int) -> tuple[str, str]:
    """First-of-month .. last feasible departure so the return stays in-month."""
    year, mon = (int(x) for x in month.split("-"))
    last_day = calendar.monthrange(year, mon)[1]
    last_out_day = max(1, last_day - nights)
    return f"{year:04d}-{mon:02d}-01", f"{year:04d}-{mon:02d}-{last_out_day:02d}"


def _iso_date(dt) -> str:
    if isinstance(dt, str):
        return dt[:10]
    return dt.date().isoformat() if isinstance(dt, datetime) else str(dt)[:10]


def _iso_dt(dt) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else str(dt)


def parse_cheapest_rt(rows: list[dict]) -> CheapestRT | None:
    """rows: [{"out_date","back_date","price","currency"}] -- price is the party total."""
    rows = [r for r in rows if r.get("price") is not None and r.get("out_date")]
    if not rows:
        return None
    best = min(rows, key=lambda r: float(r["price"]))
    return CheapestRT(
        price_total=round(float(best["price"]), 2),
        out_date=best["out_date"],
        back_date=best.get("back_date", ""),
    )


def _to_leg(d: dict) -> FlightLeg:
    return FlightLeg(
        carrier=d["carrier"],
        flight_number=d["flight_number"],
        depart_airport=d["depart_airport"],
        arrive_airport=d["arrive_airport"],
        depart_dt=d["depart_dt"],
        arrive_dt=d["arrive_dt"],
    )


def parse_exact_rt(
    records: list[dict], *, origin: str, dest: str, out_date: str, back_date: str,
    pax: int = 1,
) -> ExactFlight | None:
    """records: [{"price","currency","legs_out":[leg],"legs_back":[leg]}]."""
    records = [r for r in records if r.get("price") is not None and r.get("legs_out")]
    if not records:
        return None
    best = min(records, key=lambda r: float(r["price"]))
    return ExactFlight(
        legs_out=[_to_leg(x) for x in best.get("legs_out", [])],
        legs_back=[_to_leg(x) for x in best.get("legs_back", [])],
        price_total=round(float(best["price"]), 2),
        book_url=google_flights_url(
            origin, dest, out_date, back_date, pax,
            legs_out=best.get("legs_out") or None,
            legs_back=best.get("legs_back") or None,
        ),
    )


# ----------------------- fli object -> normalized dict ---------------------- #
def _ser_leg(leg) -> dict:
    return {
        "carrier": getattr(leg.airline, "name", str(leg.airline)),
        "flight_number": str(leg.flight_number),
        "depart_airport": getattr(leg.departure_airport, "name", str(leg.departure_airport)),
        "arrive_airport": getattr(leg.arrival_airport, "name", str(leg.arrival_airport)),
        "depart_dt": _iso_dt(leg.departure_datetime),
        "arrive_dt": _iso_dt(leg.arrival_datetime),
    }


def serialize_dates(results) -> list[dict]:
    rows: list[dict] = []
    for dp in results or []:
        date = dp.date
        out = date[0]
        back = date[1] if len(date) > 1 else None
        rows.append({
            "out_date": _iso_date(out),
            "back_date": _iso_date(back) if back is not None else "",
            "price": float(dp.price),
            "currency": dp.currency,
        })
    return rows


def serialize_results(results) -> list[dict]:
    recs: list[dict] = []
    for item in results or []:
        if isinstance(item, tuple):
            out_r, back_r = item[0], item[1]
            recs.append({
                "price": float(out_r.price),
                "currency": out_r.currency,
                "legs_out": [_ser_leg(leg) for leg in out_r.legs],
                "legs_back": [_ser_leg(leg) for leg in back_r.legs],
            })
        else:
            recs.append({
                "price": float(item.price),
                "currency": item.currency,
                "legs_out": [_ser_leg(leg) for leg in item.legs],
                "legs_back": [],
            })
    return recs


def _with_retry(fn, *args, **kwargs):
    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001  fli raises a grab-bag of errors
            last = exc
            log.debug("fli call failed (attempt %d/%d): %s", attempt + 1, _RETRIES, exc)
            if attempt < _RETRIES - 1:
                time.sleep(_BACKOFF_BASE_S * (2 ** attempt))
    assert last is not None
    raise last


# ------------------------------ provider ------------------------------------ #
class FliFlightProvider:
    async def cheapest_in_month(
        self, *, origin: str, dest: str, month: str, nights: int, pax: int
    ) -> CheapestRT | None:
        key = f"fli:coarse:{origin}:{dest}:{month}:{nights}:{pax}"
        rows = _cache.get(key)
        if rows is None:
            # fli is sync; run it off the event loop so concurrency still works.
            rows = await asyncio.to_thread(
                _with_retry, self._raw_dates, origin, dest, month, nights, pax
            )
            _cache.set(key, rows)  # JSON-native list[dict]
        return parse_cheapest_rt(rows)

    async def exact_round_trip(
        self, *, origin: str, dest: str, out_date: str, back_date: str, pax: int
    ) -> ExactFlight | None:
        key = f"fli:exact:{origin}:{dest}:{out_date}:{back_date}:{pax}"
        records = _cache.get(key)
        if records is None:
            records = await asyncio.to_thread(
                _with_retry, self._raw_exact, origin, dest, out_date, back_date, pax
            )
            _cache.set(key, records)  # JSON-native list[dict]
        return parse_exact_rt(
            records, origin=origin, dest=dest, out_date=out_date, back_date=back_date,
            pax=pax,
        )

    def raw_dates(self, origin, dest, month, nights, pax) -> list[dict]:
        return self._raw_dates(origin, dest, month, nights, pax)

    def raw_exact(self, origin, dest, out_date, back_date, pax) -> list[dict]:
        return self._raw_exact(origin, dest, out_date, back_date, pax)

    def _segments(self, origin, dest, out_date, back_date):
        from fli.models import Airport, FlightSegment

        out_air, dest_air = Airport[origin], Airport[dest]
        return [
            FlightSegment(departure_airport=[[out_air, 0]],
                          arrival_airport=[[dest_air, 0]], travel_date=out_date),
            FlightSegment(departure_airport=[[dest_air, 0]],
                          arrival_airport=[[out_air, 0]], travel_date=back_date),
        ]

    def _raw_dates(self, origin, dest, month, nights, pax) -> list[dict]:
        from fli.models import (DateSearchFilters, MaxStops, PassengerInfo,
                                SeatType, TripType)
        from fli.search import SearchDates

        from_date, to_date = _month_window(month, nights)
        seg_back = (datetime.strptime(from_date, "%Y-%m-%d")
                    + timedelta(days=nights)).date().isoformat()
        filters = DateSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=pax),
            flight_segments=self._segments(origin, dest, from_date, seg_back),
            stops=MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
            from_date=from_date,
            to_date=to_date,
            duration=nights,
        )
        return serialize_dates(SearchDates().search(filters, currency="USD"))

    def _raw_exact(self, origin, dest, out_date, back_date, pax) -> list[dict]:
        from fli.models import (FlightSearchFilters, MaxStops, PassengerInfo,
                                SeatType, SortBy, TripType)
        from fli.search import SearchFlights

        filters = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=pax),
            flight_segments=self._segments(origin, dest, out_date, back_date),
            stops=MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
            sort_by=SortBy.CHEAPEST,
        )
        return serialize_results(SearchFlights().search(filters, top_n=5, currency="USD"))
