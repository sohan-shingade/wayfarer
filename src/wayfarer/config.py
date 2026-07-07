"""Tunable knobs for the pipeline. Caps here are your defense against the
combinatorial wall and surprise spend. Adjust, don't remove.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Settings:
    # --- Caps (keep the funnel narrow; protect rate limits & token spend) ---
    max_candidates: int = 40          # brainstormer output ceiling
    max_coarse_calls: int = 40        # hard cap on flight-provider calls in coarse prune
    coarse_survivors: int = 12        # keep at most this many after flight prune
    final_plans: int = 5              # how many full plans to write

    # --- Budget model ---
    buffer_pct: float = 0.10          # discretionary food/local/activity reserve
    flight_share_ceiling: float = 0.45  # drop candidate if flights > this fraction of budget
    budget_margin: float = 0.10       # require total <= ceiling * (1 - margin) to keep
    deal_ratio: float = 0.65          # flag a fare as a "deal" if <= this * median fare

    # --- Deal-hunt (absolute, SerpApi price_insights). OFF by default: it spends
    # metered SerpApi quota. Enable via this flag, env WAYFARER_DEALHUNT=1, or --enable.
    deal_hunt_enabled: bool = False
    deal_hunt_max_calls: int = 24     # hard ceiling on SerpApi calls per scan (targets x origins)

    # --- Provider concurrency / rate limiting ---
    coarse_concurrency: int = 4       # parallel flight calls (fli is rate-limited; be gentle)
    provider_cache_ttl_s: int = 6 * 3600

    # --- Agent models (CLI aliases or full ids: claude-opus-4-8, claude-sonnet-4-6) ---
    model_brief: str = "sonnet"
    model_brainstorm: str = "sonnet"
    model_writer: str = "sonnet"      # bump to "opus" if itinerary quality matters more than speed
    model_critic: str = "sonnet"

    # --- Per-diem priors: rough $/person/day by city cost tier (food + local transport) ---
    per_diem_by_tier: dict[str, float] = field(default_factory=lambda: {
        "low": 45.0, "mid": 80.0, "high": 130.0,
    })


SETTINGS = Settings()
