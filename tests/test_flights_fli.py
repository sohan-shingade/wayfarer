"""Fast tier: the fli adapter's pure parsing path against RECORDED real responses."""
from wayfarer.models import ExactFlight
from wayfarer.providers.base import CheapestRT
from wayfarer.providers.flights_fli import parse_cheapest_rt, parse_exact_rt


def test_parse_cheapest_rt_picks_min(fli_dates):
    rt = parse_cheapest_rt(fli_dates)
    assert isinstance(rt, CheapestRT)
    # cheapest of the recorded rows
    expected = min(float(r["price"]) for r in fli_dates)
    assert rt.price_total == round(expected, 2)
    assert rt.price_total > 0
    assert rt.out_date and rt.back_date
    assert rt.out_date[:4] == "2026" and rt.back_date[:4] == "2026"


def test_parse_cheapest_rt_empty():
    assert parse_cheapest_rt([]) is None


def test_parse_exact_rt(fli_exact):
    ef = parse_exact_rt(
        fli_exact, origin="SFO", dest="KEF", out_date="2026-08-15", back_date="2026-08-22"
    )
    assert isinstance(ef, ExactFlight)
    expected = min(float(r["price"]) for r in fli_exact if r.get("legs_out"))
    assert ef.price_total == round(expected, 2)
    assert ef.price_total > 0
    assert ef.legs_out and ef.legs_back  # round trip has both directions
    leg = ef.legs_out[0]
    assert leg.carrier and leg.flight_number
    assert leg.depart_airport == "SFO"
    assert "google.com/travel/flights" in ef.book_url


def test_parse_exact_rt_empty():
    assert parse_exact_rt([], origin="SFO", dest="KEF",
                          out_date="2026-08-15", back_date="2026-08-22") is None
