"""Dev tool (NOT part of the app): capture REAL provider responses into
tests/fixtures/ so the fast-tier tests exercise genuine data with no network.

Run once, with network + SERPAPI_API_KEY available:

    python scripts/record_fixtures.py

Writes:
  tests/fixtures/fli_dates.json     -- normalized fli round-trip date search rows
  tests/fixtures/fli_exact.json     -- normalized fli round-trip exact-flight records
  tests/fixtures/serpapi_hotels.json-- raw SerpApi google_hotels payload

The fli rows are the adapter's own normalized form (real prices/dates/legs), which
is exactly what parse_cheapest_rt / parse_exact_rt consume. The SerpApi payload is
the raw response, which is what parse_cheapest_nightly / parse_exact consume.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from wayfarer.providers.flights_fli import FliFlightProvider
from wayfarer.providers.hotels_trvl import TrvlHotelProvider
from wayfarer.providers.serpapi_client import serpapi_get

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# A real route/dates that reliably returns landscape-trip data.
ORIGIN, DEST = "SFO", "KEF"
MONTH, NIGHTS, PAX = "2026-08", 7, 2
OUT_DATE, BACK_DATE = "2026-08-15", "2026-08-22"
HOTEL_Q = "Reykjavik, Iceland"


def _write(name: str, data) -> None:
    path = FIXTURES / name
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size} bytes)")


async def main() -> None:
    load_dotenv()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    fli = FliFlightProvider()

    print("recording fli date search...")
    _write("fli_dates.json", fli.raw_dates(ORIGIN, DEST, MONTH, NIGHTS, PAX))

    print("recording fli exact flight search...")
    _write("fli_exact.json", fli.raw_exact(ORIGIN, DEST, OUT_DATE, BACK_DATE, PAX))

    from wayfarer.providers.hotels_trvl import find_binary
    if find_binary():
        print("recording trvl hotels...")
        h = TrvlHotelProvider()
        _write("trvl_hotels.json", await h._search(HOTEL_Q, OUT_DATE, BACK_DATE, PAX))
    else:
        print("SKIP trvl_hotels.json: trvl binary not found")

    key = os.environ.get("SERPAPI_API_KEY")
    if not key:
        print("SKIP serpapi_hotels.json: no SERPAPI_API_KEY")
        return
    print("recording serpapi google_hotels...")
    payload = await serpapi_get({
        "engine": "google_hotels",
        "q": HOTEL_Q,
        "check_in_date": OUT_DATE,
        "check_out_date": BACK_DATE,
        "adults": str(PAX),
        "currency": "USD",
        "gl": "us",
        "hl": "en",
        "api_key": key,
    })
    _write("serpapi_hotels.json", payload)


if __name__ == "__main__":
    asyncio.run(main())
