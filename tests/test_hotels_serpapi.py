"""Fast tier: the SerpApi google_hotels pure parsers against a RECORDED payload."""
from wayfarer.models import ExactHotel
from wayfarer.providers.hotels_serpapi import (_nights, parse_cheapest_nightly,
                                              parse_exact)


def test_parse_cheapest_nightly(serpapi_hotels):
    nightly = parse_cheapest_nightly(serpapi_hotels)
    rates = [p["rate_per_night"]["extracted_lowest"]
             for p in serpapi_hotels["properties"]
             if isinstance(p.get("rate_per_night", {}).get("extracted_lowest"), (int, float))]
    assert nightly == round(min(rates), 2)
    assert nightly > 0


def test_parse_cheapest_nightly_raises_when_empty():
    import pytest
    with pytest.raises(ValueError):
        parse_cheapest_nightly({"properties": []})


def test_parse_exact(serpapi_hotels):
    nights = 7
    hotel = parse_exact(serpapi_hotels, nights)
    assert isinstance(hotel, ExactHotel)
    assert hotel.name
    assert hotel.nightly_rate == parse_cheapest_nightly(serpapi_hotels)  # cheapest property
    assert hotel.nights == nights
    assert hotel.total > 0
    assert hotel.total >= hotel.nightly_rate  # total covers at least one night


def test_nights_helper():
    assert _nights("2026-08-15", "2026-08-22") == 7
    assert _nights("2026-08-15T00:00:00", "2026-08-16T00:00:00") == 1
