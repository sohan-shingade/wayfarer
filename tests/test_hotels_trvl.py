"""Fast tier: trvl hotel parsers against a RECORDED real payload."""
import json
from pathlib import Path

import pytest

from wayfarer.models import ExactHotel
from wayfarer.providers.hotels_trvl import parse_cheapest_nightly, parse_exact

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "trvl_hotels.json"


@pytest.fixture
def trvl_hotels():
    return json.loads(FIXTURE.read_text())


def test_parse_cheapest_nightly(trvl_hotels):
    nightly = parse_cheapest_nightly(trvl_hotels)
    prices = [h["price"] for h in trvl_hotels["hotels"]
              if isinstance(h.get("price"), (int, float)) and h["price"] > 0]
    assert nightly == round(min(prices), 2)
    assert nightly > 0


def test_parse_cheapest_nightly_raises_when_empty():
    with pytest.raises(ValueError):
        parse_cheapest_nightly({"hotels": []})


def test_parse_exact(trvl_hotels):
    hotel = parse_exact(trvl_hotels, 7)
    assert isinstance(hotel, ExactHotel)
    assert hotel.name and hotel.nightly_rate == parse_cheapest_nightly(trvl_hotels)
    assert hotel.nights == 7
    assert hotel.total == round(hotel.nightly_rate * 7, 2)
    assert hotel.lat is not None and hotel.lng is not None  # trvl gives coords for the map
    assert hotel.book_url


def test_parse_exact_empty():
    assert parse_exact({"hotels": []}, 7) is None


def test_parse_exact_normalizes_booking_currency_to_usd():
    # trvl returns vendor links whose currency defaults to the viewer's locale;
    # parse_exact must pin any currency param to USD so it matches the quote.
    payload = {"hotels": [{
        "name": "Grande Rockies Resort", "price": 155.0, "lat": 51.09, "lon": -115.35,
        "booking_url": "https://www.trivago.com/en-US/lm/grande-rockies?currencyCode=EUR&dr=20260829-20260901;rc-1-4",
    }]}
    hotel = parse_exact(payload, 3)
    assert "currencyCode=USD" in hotel.book_url and "EUR" not in hotel.book_url
    assert "rc-1-4" in hotel.book_url  # preserves the rest of the deep link
