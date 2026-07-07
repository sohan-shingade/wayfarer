"""Deterministic budget math. No LLM here on purpose: this is where correctness
matters and you want it testable and repeatable.
"""
from __future__ import annotations

from ..models import Budget


def assemble_budget(
    *,
    flights: float,
    nightly_rate: float,
    nights: int,
    per_diem_pp_per_day: float,
    pax: int,
    buffer_pct: float = 0.10,
) -> Budget:
    lodging = nightly_rate * nights
    per_diem = per_diem_pp_per_day * pax * nights
    subtotal = flights + lodging + per_diem
    buffer = round(subtotal * buffer_pct, 2)
    return Budget(
        flights=round(flights, 2),
        lodging=round(lodging, 2),
        per_diem=round(per_diem, 2),
        buffer=buffer,
    )


def fits(budget: Budget, ceiling: float, margin: float = 0.0) -> bool:
    return budget.total <= ceiling * (1.0 - margin)


def rebudget_from_exact(
    *,
    flight_total: float,
    hotel_total: float,
    per_diem: float,
    buffer_pct: float = 0.10,
) -> Budget:
    """Recompute the budget from EXACT flight + hotel prices (the numbers the plan
    actually ships), keeping the tier-based per-diem. The coarse budget is fine for
    ranking, but the presented plan should sum its real, bookable line items so the
    total matches what the user sees -- not the coarse estimate it was ranked on.
    """
    subtotal = flight_total + hotel_total + per_diem
    return Budget(
        flights=round(flight_total, 2),
        lodging=round(hotel_total, 2),
        per_diem=round(per_diem, 2),
        buffer=round(subtotal * buffer_pct, 2),
    )
