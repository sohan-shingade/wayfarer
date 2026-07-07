"""Deep-link builders: exact flight (Google Flights tfs) + exact hotel link."""
import base64
from urllib.parse import parse_qs, unquote, urlparse

from wayfarer.text import force_usd, google_flights_url, hotel_booking_url


def _tfs_bytes(url: str) -> bytes:
    tfs = parse_qs(urlparse(url).query)["tfs"][0]
    return base64.urlsafe_b64decode(tfs + "=" * ((4 - len(tfs) % 4) % 4))


def test_flight_url_search_encodes_pax_and_route():
    url = google_flights_url("SFO", "YYC", "2026-08-17", "2026-08-22", pax=4)
    assert "/travel/flights/search?tfs=" in url and "q=Flights" not in url
    raw = _tfs_bytes(url)
    assert b"SFO" in raw and b"YYC" in raw
    assert b"2026-08-17" in raw and b"2026-08-22" in raw
    assert raw.count(b"\x40\x01") == 4          # four ADULT passengers (field 8 = 0x40)


def test_flight_url_pax_changes_payload():
    one = google_flights_url("SFO", "YYC", "2026-08-17", "2026-08-22", pax=1)
    four = google_flights_url("SFO", "YYC", "2026-08-17", "2026-08-22", pax=4)
    assert one != four


def test_flight_url_exact_segments_match_real_share_link():
    """With legs, the tfs must reproduce the itinerary a real /s/ link decodes to."""
    legs_out = [
        {"depart_airport": "SFO", "arrive_airport": "YVR", "depart_dt": "2026-08-17T19:30:00",
         "carrier": "AC", "flight_number": "573"},
        {"depart_airport": "YVR", "arrive_airport": "YYC", "depart_dt": "2026-08-17T23:10:00",
         "carrier": "AC", "flight_number": "228"},
    ]
    legs_back = [
        {"depart_airport": "YYC", "arrive_airport": "SFO", "depart_dt": "2026-08-22T19:55:00",
         "carrier": "WS", "flight_number": "1504"},
    ]
    url = google_flights_url("SFO", "YYC", "2026-08-17", "2026-08-22", pax=4,
                             legs_out=legs_out, legs_back=legs_back)
    tfs = parse_qs(urlparse(url).query)["tfs"][0]
    # Real shared link for exactly this itinerary (4 adults), minus Google's trailing
    # response metadata (price block); our tfs is its leading itinerary slice.
    real = ("CAIQAhpgEgoyMDI2LTA4LTE3Ih8KA1NGTxIKMjAyNi0wOC0xNxoDWVZSKgJBQzIDNTcz"
            "Ih8KA1lWUhIKMjAyNi0wOC0xNxoDWVlDKgJBQzIDMjI4agcIARIDU0ZPcgcIARIDWVlD"
            "GkASCjIwMjYtMDgtMjIiIAoDWVlDEgoyMDI2LTA4LTIyGgNTRk8qAldTMgQxNTA0agcI"
            "ARIDWVlDcgcIARIDU0ZPQAFAAUABQAFIAQ")
    assert real.startswith(tfs)
    raw = _tfs_bytes(url)
    assert b"AC" in raw and b"573" in raw and b"WS" in raw and b"1504" in raw


def test_hotel_url_carries_property_dates_guests():
    url = hotel_booking_url("Peaks Hotel & Suites", "Banff, Alberta, Canada",
                            "2026-08-18", "2026-08-22", pax=4)
    q = parse_qs(urlparse(url).query)
    assert "Peaks Hotel & Suites" in unquote(q["ss"][0])
    assert q["checkin"] == ["2026-08-18"] and q["checkout"] == ["2026-08-22"]
    assert q["group_adults"] == ["4"]
    assert q["selected_currency"] == ["USD"]


def test_force_usd_rewrites_known_currency_params():
    # Kiwi (currency=eur), Trivago (currencyCode), Google (curr), Booking (selected_currency)
    assert "currency=USD" in force_usd("https://www.kiwi.com/en/booking/?currency=eur&token=abc")
    assert force_usd("https://x/lm/h?currencyCode=GBP&dr=1").count("currencyCode=USD") == 1
    assert "curr=USD" in force_usd("https://www.google.com/travel/flights/search?tfs=x&curr=EUR")


def test_force_usd_preserves_other_params_and_token():
    out = force_usd("https://www.kiwi.com/en/booking/?direct=true&currency=eur&token=XYZ123")
    q = parse_qs(urlparse(out).query)
    assert q["currency"] == ["USD"] and q["token"] == ["XYZ123"] and q["direct"] == ["true"]


def test_force_usd_leaves_currencyless_links_untouched():
    # A short kiwi.com/u/<id> link carries no query param — currency is server-side.
    short = "https://kiwi.com/u/5cyq9z"
    assert force_usd(short) == short
    assert force_usd("") == ""
