"""Live tier (acceptance #2): the genuine end-to-end against real services -- real
fli flights, real SerpApi google_hotels, real `claude -p`.

Excluded from the default run (pyproject sets `addopts = -m 'not live'`). Run with:

    pytest -m live

Skips cleanly unless SERPAPI_API_KEY, network, and the `claude` CLI are all
present. ANTHROPIC_API_KEY must be UNSET so agents bill the subscription.
"""
import os
import shutil

import pytest

from wayfarer.agents.runtime import ClaudeCLIRuntime
from wayfarer.config import SETTINGS
from wayfarer.orchestrator import Orchestrator
from wayfarer.providers.flights_fli import FliFlightProvider
from wayfarer.providers.hotels_serpapi import SerpApiHotelProvider
from wayfarer.providers.priors import StaticPriors

pytestmark = pytest.mark.live

REQUEST = "vacation for 2, budget 3k total, anytime in august, want insane landscapes"


def _have_network() -> bool:
    import socket
    try:
        socket.create_connection(("serpapi.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


def _claude_logged_in() -> bool:
    """Probe `claude -p` (same isolation flags as the runtime, minus --bare which
    breaks auth): returns False on the 'Not logged in' result so the test skips
    rather than fails when there's no subscription."""
    import json
    import subprocess

    from wayfarer.agents.runtime import subscription_env
    try:
        out = subprocess.run(
            ["claude", "-p", "Respond with the single word: ready", "--output-format",
             "json", "--model", SETTINGS.model_brief, "--max-turns", "6",
             "--setting-sources", "", "--strict-mcp-config"],
            capture_output=True, text=True, timeout=90, env=subscription_env(),
        )
        data = json.loads(out.stdout or "{}")
        return out.returncode == 0 and not data.get("is_error")
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.asyncio
async def test_live_end_to_end():
    if not os.environ.get("SERPAPI_API_KEY"):
        pytest.skip("SERPAPI_API_KEY not set")
    if shutil.which("claude") is None:
        pytest.skip("`claude` CLI not on PATH")
    if not _have_network():
        pytest.skip("no network")
    if not _claude_logged_in():
        pytest.skip("`claude` not logged in on a subscription (run `claude login`)")

    def _elicit(raw):
        if not raw.get("origin_iata"):
            raw["origin_iata"] = "SFO"
        if raw.get("long_haul_ok") is None:
            raw["long_haul_ok"] = True
        if raw.get("hard_ceiling") is None:
            raw["hard_ceiling"] = True
        return raw

    # Current Claude Code reports a notional total_cost_usd even on subscription
    # runs, so disable the API-billing guard here (env is already scrubbed of
    # ANTHROPIC_* keys). Set WAYFARER_ALLOW_COST=1 to mirror this in the CLI.
    orch = Orchestrator(
        runtime=ClaudeCLIRuntime(model=SETTINGS.model_brief, fail_on_api_billing=False),
        flights=FliFlightProvider(),
        hotels=SerpApiHotelProvider(),
        priors=StaticPriors(),
        settings=SETTINGS,
        elicit=_elicit,
    )
    plans = await orch.plan_trip(REQUEST)

    assert 4 <= len(plans) <= 5, f"expected 4-5 plans, got {len(plans)}"
    for p in plans:
        assert p.budget.total <= 3000, f"{p.destination} over ceiling: {p.budget.total}"
        assert p.itinerary, f"{p.destination} has empty itinerary"
        assert p.flight.price_total > 0
        assert p.hotel.nightly_rate > 0
