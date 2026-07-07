"""Provider interfaces. Code depends on these, never on a concrete vendor, so you
can start on free/fragile fli and swap to SerpApi or Amadeus without touching the
engine or orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ..models import ExactFlight, ExactHotel


@dataclass
class CheapestRT:
    price_total: float       # party total
    out_date: str
    back_date: str


class FlightProvider(Protocol):
    async def cheapest_in_month(
        self, *, origin: str, dest: str, month: str, nights: int, pax: int
    ) -> CheapestRT | None:
        """Coarse: cheapest round-trip in the month. Approximate is fine (pruning)."""
        ...

    async def exact_round_trip(
        self, *, origin: str, dest: str, out_date: str, back_date: str, pax: int
    ) -> ExactFlight | None:
        """Exact: specific flights with numbers, times, price for the finalists."""
        ...


class HotelProvider(Protocol):
    # `q` is a free-text location (e.g. "Reykjavik, Iceland"). SerpApi google_hotels
    # takes free text, not an Amadeus city code, so the engine passes the destination
    # name straight through -- no IATA->city table to maintain.
    async def cheapest_nightly(
        self, *, q: str, check_in: str, check_out: str, pax: int
    ) -> float:
        """Coarse lodging estimate (nightly rate) used in budget assembly."""
        ...

    async def exact_hotel(
        self, *, q: str, check_in: str, check_out: str, pax: int
    ) -> ExactHotel | None:
        """Named property with rate for the finalists."""
        ...


class PriorsProvider(Protocol):
    def cost_tier(self, city: str, country: str) -> Literal["low", "mid", "high"]:
        ...

    def geocode(self, city: str, country: str) -> tuple[float, float]:
        """lat, lng. Only needed if you later add the Amadeus activities API."""
        ...
