"""Deal-hunt mode: scan aspirational destinations from your origins for fares
BELOW their typical historical range (SerpApi google_flights price_insights) --
pure error-fare hunting, ignoring vibe/budget. Separate from the plan pipeline.

    wayfarer-deals --origins SFO,OAK --month 2026-10 --nights 7

Honors the persistent cache, so re-scanning the same routes within the TTL is free.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from .config import SETTINGS
from .engine.deals import score_deal
from .providers.flights_serpapi import SerpApiFlightProvider
from .text import scenario_id, slugify

# Curated bucket-list destinations (the kind of place a sub-$400 fare would be a
# steal). (city, region, country, iata). Extend freely.
DEAL_TARGETS: list[tuple[str, str, str, str]] = [
    ("Tokyo", "", "Japan", "HND"),
    ("Reykjavik", "", "Iceland", "KEF"),
    ("Paris", "", "France", "CDG"),
    ("Rome", "", "Italy", "FCO"),
    ("Lisbon", "", "Portugal", "LIS"),
    ("Barcelona", "", "Spain", "BCN"),
    ("Oslo", "", "Norway", "OSL"),
    ("Queenstown", "Otago", "New Zealand", "ZQN"),
    ("Santiago", "", "Chile", "SCL"),
    ("Lima", "", "Peru", "LIM"),
    ("Cape Town", "", "South Africa", "CPT"),
    ("Seoul", "", "South Korea", "ICN"),
    ("Bangkok", "", "Thailand", "BKK"),
    ("Athens", "", "Greece", "ATH"),
    ("Zurich", "", "Switzerland", "ZRH"),
    ("Mexico City", "", "Mexico", "MEX"),
]


def _month_dates(month: str, nights: int) -> tuple[str, str]:
    year, mon = (int(x) for x in month.split("-"))
    out = f"{year:04d}-{mon:02d}-15"
    back = (datetime.strptime(out, "%Y-%m-%d") + timedelta(days=nights)).date().isoformat()
    return out, back


async def hunt(
    *, origins: list[str], month: str, nights: int, pax: int,
    provider: SerpApiFlightProvider, max_targets: int, min_discount: float,
    targets: list[tuple[str, str, str, str]] = DEAL_TARGETS,
) -> list[dict]:
    out_date, back_date = _month_dates(month, nights)
    targets = targets[:max_targets]
    sem = asyncio.Semaphore(SETTINGS.coarse_concurrency)

    async def scan(t) -> dict | None:
        city, region, country, iata = t
        best = None  # (origin, insights)
        for origin in origins:
            async with sem:
                try:
                    pi = await provider.price_insights(
                        origin=origin, dest=iata,
                        out_date=out_date, back_date=back_date, pax=pax,
                    )
                except Exception:  # noqa: BLE001  one route failing must not kill the scan
                    continue
            if pi and (best is None or (pi["price"] or 1e9) < (best[1]["price"] or 1e9)):
                best = (origin, pi)
        if best is None:
            return None
        origin, pi = best
        verdict = score_deal(pi["price"], pi["typical_low"], pi["typical_high"], pi["price_level"])
        if not verdict["is_deal"] or verdict["discount_pct"] < min_discount:
            return None
        return {
            "destination": f"{city}, {country}", "iata": iata, "origin": origin,
            "out_date": out_date, "back_date": back_date, **verdict,
        }

    results = await asyncio.gather(*(scan(t) for t in targets))
    deals = [d for d in results if d]
    deals.sort(key=lambda d: d["discount_pct"], reverse=True)
    return deals


def _write_deals(deals: list[dict], origins, month, nights, pax, out_root) -> Path:
    sid = scenario_id(json.dumps({"o": sorted(origins), "m": month, "n": nights, "p": pax}, sort_keys=True))
    run_dir = Path(out_root) / f"deals_{month}_{slugify('-'.join(origins))}_{sid}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "deals.json").write_text(json.dumps(deals, indent=2), encoding="utf-8")
    lines = [f"# Flight deals · {month} · {nights} nights · from {', '.join(origins)}", ""]
    if not deals:
        lines.append("No below-typical fares found in this scan.")
    else:
        lines += ["| Destination | From | Fare | Typical low | Discount | Level |",
                  "| --- | --- | ---: | ---: | ---: | --- |"]
        for d in deals:
            tl = f"${d['typical_low']:,.0f}" if d["typical_low"] else "—"
            lines.append(f"| {d['destination']} | {d['origin']} | ${d['price']:,.0f} | {tl} | "
                         f"{d['discount_pct']:.0f}% | {d['price_level']} |")
    (run_dir / "deals.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_dir


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Hunt below-typical (deal) flights from your origins.")
    ap.add_argument("--origins", default="SFO", help="comma-separated origin IATAs")
    ap.add_argument("--month", required=True, help='travel month "YYYY-MM"')
    ap.add_argument("--nights", type=int, default=7)
    ap.add_argument("--pax", type=int, default=2)
    ap.add_argument("--max-targets", type=int, default=8,
                    help="cap destinations scanned (quota: max-targets x origins SerpApi calls)")
    ap.add_argument("--min-discount", type=float, default=0.0,
                    help="only show fares at least this %% below typical-low")
    ap.add_argument("--enable", action="store_true",
                    help="opt in to spending SerpApi quota for this scan")
    ap.add_argument("--out", default="runs")
    args = ap.parse_args()

    # Toggle: OFF unless explicitly enabled (flag, env, or settings) so deal-hunt
    # never quietly burns metered SerpApi quota.
    enabled = (args.enable or SETTINGS.deal_hunt_enabled
               or os.environ.get("WAYFARER_DEALHUNT") == "1")
    if not enabled:
        raise SystemExit(
            "Deal-hunt is off (it spends SerpApi quota). Enable it with --enable, "
            "WAYFARER_DEALHUNT=1, or Settings.deal_hunt_enabled=True.")

    key = os.environ.get("SERPAPI_API_KEY")
    if not key:
        raise SystemExit("SERPAPI_API_KEY required for deal-hunt (uses google_flights price_insights).")
    origins = [a.strip().upper() for a in args.origins.split(",") if a.strip()] or ["SFO"]

    # Hard cap: clamp targets so total calls stay under the quota ceiling.
    max_targets = min(args.max_targets, len(DEAL_TARGETS))
    call_cap = max(1, SETTINGS.deal_hunt_max_calls // len(origins))
    if max_targets > call_cap:
        print(f"NOTE: clamping to {call_cap} destinations to stay under the "
              f"{SETTINGS.deal_hunt_max_calls}-call quota ceiling (was {max_targets}).")
        max_targets = call_cap
    args.max_targets = max_targets

    provider = SerpApiFlightProvider(api_key=key)
    print(f"Scanning {max_targets} destinations from "
          f"{', '.join(origins)} for {args.month}... "
          f"(~{max_targets * len(origins)} SerpApi calls)")
    deals = asyncio.run(hunt(
        origins=origins, month=args.month, nights=args.nights, pax=args.pax,
        provider=provider, max_targets=args.max_targets, min_discount=args.min_discount,
    ))
    if not deals:
        print("No below-typical fares found. Try a different month or more --max-targets.")
    for d in deals:
        tl = f" (typical low ${d['typical_low']:,.0f})" if d["typical_low"] else ""
        print(f"  🔥 {d['destination']:24} {d['origin']}→{d['iata']}  "
              f"${d['price']:,.0f}{tl}  -{d['discount_pct']:.0f}%  [{d['price_level']}]")
    run_dir = _write_deals(deals, origins, args.month, args.nights, args.pax, args.out)
    print(f"\nSaved deals to {run_dir}/")


if __name__ == "__main__":
    main()
