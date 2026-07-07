"""Static priors: per-diem cost tier and geocoding. No API needed for v1.

Seed table below is intentionally tiny. TODO: expand, or replace cost_tier with a
lookup against a cost-of-living dataset (e.g. a bundled CSV) and geocode() with a
local airport/city coordinate table.
"""
from __future__ import annotations

from typing import Literal

# Rough $/person/day cost tier by country. Skewed toward the destinations the
# brainstormer keeps returning for "insane landscapes" trips. Default is "mid".
_TIER: dict[str, Literal["low", "mid", "high"]] = {
    # --- low ---
    "Portugal": "low",
    "Spain": "low",
    "Greece": "low",
    "Turkey": "low",
    "Morocco": "low",
    "Mexico": "low",
    "Peru": "low",
    "Bolivia": "low",
    "Nepal": "low",
    "India": "low",
    "Indonesia": "low",
    "Vietnam": "low",
    "Thailand": "low",
    "Georgia": "low",
    "Albania": "low",
    "Montenegro": "low",
    "Colombia": "low",
    "Guatemala": "low",
    "South Africa": "low",
    "Namibia": "low",
    "Kyrgyzstan": "low",
    # --- mid ---
    "Italy": "mid",
    "United Kingdom": "mid",
    "Ireland": "mid",
    "France": "mid",
    "Germany": "mid",
    "Austria": "mid",
    "Slovenia": "mid",
    "Croatia": "mid",
    "Canada": "mid",
    "United States": "mid",
    "Chile": "mid",
    "Argentina": "mid",
    "Japan": "mid",
    "South Korea": "mid",
    "Costa Rica": "mid",
    "Jordan": "mid",
    "Tanzania": "mid",
    # --- high ---
    "Iceland": "high",
    "Norway": "high",
    "Switzerland": "high",
    "Sweden": "high",
    "Finland": "high",
    "Denmark": "high",
    "New Zealand": "high",
    "Australia": "high",
    "Singapore": "high",
}


class StaticPriors:
    def cost_tier(self, city: str, country: str) -> Literal["low", "mid", "high"]:
        return _TIER.get(country, "mid")

    def geocode(self, city: str, country: str) -> tuple[float, float]:
        raise NotImplementedError("add a city/airport coordinate table if you add activities")
