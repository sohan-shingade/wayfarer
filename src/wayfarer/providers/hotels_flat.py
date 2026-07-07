"""No-key fallback HotelProvider: a LABELED degraded estimate, not a mock.

When no SERPAPI_API_KEY is present the pipeline still needs a lodging number to
assemble budgets. This returns a flat nightly prior and clearly marks the
resulting hotel as an estimate (name prefixed "(estimate)", empty book link) so a
plan built on it is never mistaken for a real, bookable rate.
"""
from __future__ import annotations

from datetime import datetime

from ..models import ExactHotel


def _nights(check_in: str, check_out: str) -> int:
    a = datetime.strptime(check_in[:10], "%Y-%m-%d")
    b = datetime.strptime(check_out[:10], "%Y-%m-%d")
    return max(1, (b - a).days)


class FlatRateHotelProvider:
    def __init__(self, nightly: float = 140.0) -> None:
        self.nightly = nightly

    async def cheapest_nightly(self, *, q: str, check_in: str, check_out: str, pax: int) -> float:
        return self.nightly

    async def exact_hotel(
        self, *, q: str, check_in: str, check_out: str, pax: int
    ) -> ExactHotel | None:
        nights = _nights(check_in, check_out)
        return ExactHotel(
            name=f"(estimate) typical {q} hotel",
            nightly_rate=self.nightly,
            nights=nights,
            total=round(self.nightly * nights, 2),
            book_url="",
        )
