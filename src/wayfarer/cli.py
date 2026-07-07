"""Entry point. Usage:

    wayfarer "vacation for 2, budget 3k total, anytime in august, want insane landscapes"

Wires the concrete providers + the Claude CLI runtime, runs the pipeline, prints plans.
Default vendors: fli for flights (free), SerpApi google_hotels for lodging. With no
SERPAPI_API_KEY the lodging falls back to a labeled flat-rate estimate. Swap
FliFlightProvider -> SerpApiFlightProvider and ClaudeCLIRuntime -> an API runtime
for production without touching the orchestrator or engine.
"""
from __future__ import annotations

import argparse
import asyncio
import os

import webbrowser

from .agents.runtime import ClaudeCLIRuntime
from .config import SETTINGS
from .orchestrator import Orchestrator
from .output import write_run
from .providers.flights_fli import FliFlightProvider
from .providers.hotels_flat import FlatRateHotelProvider
from .providers.hotels_serpapi import SerpApiHotelProvider
from .providers.hotels_trvl import TrvlHotelProvider, find_binary
from .providers.priors import StaticPriors


def _load_env() -> None:
    """Best-effort load of a local .env so SERPAPI_API_KEY is available."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:  # noqa: BLE001  dotenv is optional; env may be set already
        pass


def _make_hotels():
    # Preference: trvl (free, keyless) -> SerpApi (key) -> flat estimate (no-key).
    # Override with WAYFARER_HOTELS=trvl|serpapi|flat.
    choice = os.environ.get("WAYFARER_HOTELS", "").lower()
    if choice == "serpapi" or (choice == "" and not find_binary() and os.environ.get("SERPAPI_API_KEY")):
        return SerpApiHotelProvider()
    if choice == "flat":
        return FlatRateHotelProvider()
    if choice in ("", "trvl") and find_binary():
        return TrvlHotelProvider()
    if os.environ.get("SERPAPI_API_KEY"):
        return SerpApiHotelProvider()
    print("WARNING: no trvl binary and no SERPAPI_API_KEY -> flat-rate lodging "
          "estimates (plans show '(estimate)' hotels, not real bookable rates).")
    return FlatRateHotelProvider()


def _cli_elicit(raw: dict) -> dict:
    """The two-question gate, on the terminal. A web UI would replace this."""
    if not raw.get("origin_iata"):
        ans = input("Departure airport IATA (e.g. SFO; comma-separate to check several): ")
        codes = [a.strip().upper() for a in ans.split(",") if a.strip()]
        raw["origin_iata"] = codes[0] if codes else ""
        if len(codes) > 1:
            raw["origins"] = codes
    if raw.get("long_haul_ok") is None:
        raw["long_haul_ok"] = input("Long-haul (10h+) OK? [y/N]: ").strip().lower() == "y"
    if raw.get("hard_ceiling") is None:
        raw["hard_ceiling"] = input("Is the budget a hard ceiling? [Y/n]: ").strip().lower() != "n"
    return raw


def _print_plan(i: int, plan) -> None:
    b = plan.budget
    deal = "  🔥 DEAL" if plan.is_deal else ""
    print(f"\n=== Plan {i}: {plan.destination}  [{plan.status}]{deal} ===")
    print(f"  {plan.summary}")
    print(f"  flights ${b.flights:.0f} | lodging ${b.lodging:.0f} | "
          f"per-diem ${b.per_diem:.0f} | buffer ${b.buffer:.0f}  ->  TOTAL ${b.total:.0f}")
    if plan.critic_notes:
        print(f"  critic: {plan.critic_notes}")
    for d in plan.itinerary:
        print(f"   day {d.day}: {d.title}")


def _overrides(args) -> dict:
    """CLI flags that override the LLM's parse (None = let the parser decide)."""
    ov: dict = {}
    if args.pax is not None:
        ov["pax"] = args.pax
    if args.budget is not None:
        ov["budget_total"] = args.budget
    if args.month is not None:
        ov["month"] = args.month
    if args.nights is not None:
        ov["nights"] = args.nights
    if args.origins:
        codes = [a.strip().upper() for a in args.origins.split(",") if a.strip()]
        if codes:
            ov["origin_iata"] = codes[0]
            ov["origins"] = codes
    return ov


def main() -> None:
    ap = argparse.ArgumentParser(description="Agentic budget-bounded trip planner (plan-only).")
    ap.add_argument("request", help="natural-language vacation request")
    ap.add_argument("--pax", type=int, help="number of travelers (overrides parse)")
    ap.add_argument("--budget", type=float, help="total budget USD (overrides parse)")
    ap.add_argument("--month", help='travel month "YYYY-MM" (overrides parse)')
    ap.add_argument("--nights", type=int, help="nights (overrides parse)")
    ap.add_argument("--origins", help="comma-separated origin IATAs, e.g. SFO,OAK,SJC")
    ap.add_argument("--out", default="runs", help="output root directory (default: runs)")
    ap.add_argument("--open", action="store_true", help="open the HTML viewer when done")
    ap.add_argument(
        "--allow-cost", action="store_true",
        default=os.environ.get("WAYFARER_ALLOW_COST") == "1",
        help="Proceed even if claude -p reports a positive total_cost_usd. Current "
             "Claude Code versions report a notional cost on subscription runs too, "
             "so the default guard (which assumes positive cost == API billing) blocks "
             "every run. Set this only after confirming via /status that you're on "
             "subscription auth (or WAYFARER_ALLOW_COST=1).",
    )
    args = ap.parse_args()

    _load_env()
    # The runtime still strips ANTHROPIC_API_KEY/AUTH_TOKEN/BASE_URL regardless.
    runtime = ClaudeCLIRuntime(
        model=SETTINGS.model_brief, fail_on_api_billing=not args.allow_cost
    )
    orch = Orchestrator(
        runtime=runtime,
        flights=FliFlightProvider(),
        hotels=_make_hotels(),
        priors=StaticPriors(),
        settings=SETTINGS,
        elicit=_cli_elicit,
    )
    plans, brief = asyncio.run(orch.plan_trip_with_brief(args.request, _overrides(args)))
    if not plans:
        print("No destinations fit that budget. Try raising it or relaxing the dates/vibe.")
        return
    for i, plan in enumerate(plans, 1):
        _print_plan(i, plan)

    run_dir = write_run(plans, brief, out_root=args.out)
    index = run_dir / "index.html"
    print(f"\nSaved {len(plans)} plans to {run_dir}/")
    print(f"  open the visual map view:  {index}")
    if args.open:
        webbrowser.open(index.resolve().as_uri())


if __name__ == "__main__":
    main()
