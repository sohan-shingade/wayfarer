"""HotelProvider backed by the `trvl` CLI (https://github.com/MikkoParkkola/trvl).

Free, no API key: trvl aggregates Google Hotels + Agoda + Booking + others via
native protocols (Chrome TLS fingerprinting), which is the reverse-engineering we
chose not to hand-build. We shell out to the binary (like the claude -p runtime)
and parse its JSON, staying behind the HotelProvider interface.

`trvl hotels "<q>" --checkin --checkout --guests N --currency USD --format json`
returns `{"hotels":[{name, price (nightly, price_basis room_nightly), currency,
stars, lat, lon, booking_url, ...}]}`. Parsing is pure so the fast tier can run a
recorded payload through the same path.

License note: trvl is PolyForm Noncommercial — fine for personal/plan-only use.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime

from ..config import SETTINGS
from ..models import ExactHotel
from ..text import force_usd
from .cache import get_cache

log = logging.getLogger(__name__)
_cache = get_cache(SETTINGS.provider_cache_ttl_s)


def _nights(check_in: str, check_out: str) -> int:
    a = datetime.strptime(check_in[:10], "%Y-%m-%d")
    b = datetime.strptime(check_out[:10], "%Y-%m-%d")
    return max(1, (b - a).days)


def _price(h: dict) -> float | None:
    p = h.get("price")
    return float(p) if isinstance(p, (int, float)) and p > 0 else None


def parse_cheapest_nightly(payload: dict) -> float:
    rates = [r for h in (payload.get("hotels") or []) if (r := _price(h)) is not None]
    if not rates:
        raise ValueError("no hotel prices in trvl payload")
    return round(min(rates), 2)


def parse_exact(payload: dict, nights: int) -> ExactHotel | None:
    best: dict | None = None
    best_rate: float | None = None
    for h in payload.get("hotels") or []:
        rate = _price(h)
        if rate is None:
            continue
        if best_rate is None or rate < best_rate:
            best_rate, best = rate, h
    if best is None or best_rate is None:
        return None
    lat, lng = best.get("lat"), best.get("lon")
    return ExactHotel(
        name=best.get("name", "(unnamed)"),
        nightly_rate=round(best_rate, 2),
        nights=nights,
        total=round(best_rate * nights, 2),
        # trvl hands back a raw vendor link (Trivago/Agoda/Google Hotels) whose
        # currency defaults to the viewer's locale; pin it to USD to match the quote.
        book_url=force_usd(best.get("booking_url", "")),
        lat=float(lat) if isinstance(lat, (int, float)) else None,
        lng=float(lng) if isinstance(lng, (int, float)) else None,
    )


def _trvl_env() -> dict[str, str]:
    """Env for the trvl subprocess with browser-cookie fallbacks OFF.

    trvl's browser-assisted fallback reads Chrome's "Safe Storage" key from the
    macOS login keychain, which pops a keychain-access prompt on every run (the
    binary is ad-hoc/linker-signed, so "Always Allow" never sticks). Our hotel
    search is API-first and needs none of that, so we hard-disable both browser
    paths -> trvl never touches the keychain -> no prompt, no blocked run.
    Override by exporting these yourself before running.
    """
    env = dict(os.environ)
    env.setdefault("TRVL_ALLOW_BROWSER_COOKIES", "0")
    env.setdefault("TRVL_ALLOW_BROWSER_FALLBACKS", "0")
    return env


def find_binary() -> str | None:
    """Locate the trvl binary (PATH, $TRVL_BIN, or the default go install dir)."""
    env = os.environ.get("TRVL_BIN")
    if env and os.path.exists(env):
        return env
    found = shutil.which("trvl")
    if found:
        return found
    gobin = os.path.expanduser("~/go/bin/trvl")
    return gobin if os.path.exists(gobin) else None


class TrvlHotelProvider:
    def __init__(self, binary: str | None = None, timeout_s: float = 90.0) -> None:
        self.binary = binary or find_binary()
        if not self.binary:
            raise ValueError("trvl binary not found (install: go install "
                             "github.com/MikkoParkkola/trvl/cmd/trvl@latest)")
        self.timeout_s = timeout_s

    async def _search(self, q: str, check_in: str, check_out: str, pax: int) -> dict:
        key = f"trvl:hotels:{q}:{check_in}:{check_out}:{pax}"
        if (cached := _cache.get(key)) is not None:
            return cached
        proc = await asyncio.create_subprocess_exec(
            self.binary, "hotels", q,
            "--checkin", check_in[:10], "--checkout", check_out[:10],
            "--guests", str(pax), "--currency", "USD", "--sort", "cheapest",
            "--format", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=_trvl_env(),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"trvl hotels timed out after {self.timeout_s}s")
        if proc.returncode != 0:
            raise RuntimeError(f"trvl hotels exited {proc.returncode}: "
                               f"{err.decode(errors='replace')[:300]}")
        data = json.loads(out.decode())  # trvl logs warnings to stderr; stdout is clean JSON
        _cache.set(key, data)
        return data

    async def cheapest_nightly(self, *, q: str, check_in: str, check_out: str, pax: int) -> float:
        return parse_cheapest_nightly(await self._search(q, check_in, check_out, pax))

    async def exact_hotel(
        self, *, q: str, check_in: str, check_out: str, pax: int
    ) -> ExactHotel | None:
        data = await self._search(q, check_in, check_out, pax)
        return parse_exact(data, _nights(check_in, check_out))
