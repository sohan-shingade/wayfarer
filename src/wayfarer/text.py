"""Tiny pure string helpers (no vendor, no I/O) shared across stages."""
from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


# Query params different booking vendors use to carry the display currency.
# A pass-through third-party link (trvl gives us Kiwi/Trivago/Agoda URLs) defaults
# its currency by the viewer's IP/locale — a US user on a Kiwi link lands on EUR.
# We normalize every one we recognize to USD so quoted prices match the plan.
_CURRENCY_PARAMS = frozenset({
    "curr", "currency", "currencycode", "selected_currency", "selectedcurrency",
})


def force_usd(url: str) -> str:
    """Rewrite a booking URL's currency query param to USD, preserving everything else.

    Only touches params that already exist (case-insensitive key match), so a URL
    whose currency is server-side (e.g. a short ``kiwi.com/u/<id>`` link with no
    query string) is returned unchanged — the caller should prefer a link that
    carries the currency explicitly. Pure string transform, no vendor import, no I/O.
    """
    if not url or "?" not in url:
        return url
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not any(k.lower() in _CURRENCY_PARAMS for k, _ in pairs):
        return url
    fixed = [(k, "USD" if k.lower() in _CURRENCY_PARAMS else v) for k, v in pairs]
    return urlunsplit(parts._replace(query=urlencode(fixed)))


def place_query(city: str, country: str, region: str = "") -> str:
    """Build a hotel-search query from a candidate's city (+ region + country).

    Two cleanups:
    - Strip a landmark in parentheses (e.g. "Denver (Rocky Mountain NP)") that
      SerpApi google_hotels can't resolve ("hasn't returned any results").
    - Include the region/state so an ambiguous city name resolves to the intended
      place: "Jackson, United States" picks Jackson MS, but "Jackson, Wyoming,
      United States" picks the Tetons town next to airport JAC.
    """
    city = re.sub(r"\s*\([^)]*\)", "", city).strip().strip(",").strip()
    region = region.strip().strip(",").strip()
    parts = [p for p in (city, region, country) if p]
    return ", ".join(parts)


# --- Google Flights `tfs` deep link -------------------------------------------
# `tfs` is a base64 (URL-safe) protobuf encoding a Google Flights itinerary. A
# plain `?q=...` link defaults to 1 passenger; we build the real tfs instead.
#
# Two shapes, both proto3, both verified against real Google links:
#  * search (no specific flights): FlightData{ date=2, from_airport=13, to_airport=14 }
#  * exact itinerary (our default when fli returns legs): FlightData also carries
#    one segment per leg in field 4 { from=1, date=2, to=3, airline=5, flight_no=6 }
#    — this is what a shared `/travel/flights/s/<token>` link decodes to.
# Info{ f1=2, f2=2, data=3 (repeated), passengers=8 (repeated ADULT=1), seat=9=ECONOMY }.
def _pb_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        out.append(b | 0x80 if value else b)
        if not value:
            return bytes(out)


def _pb_len(field: int, payload: bytes) -> bytes:  # wire type 2
    return _pb_varint((field << 3) | 2) + _pb_varint(len(payload)) + payload


def _pb_int(field: int, value: int) -> bytes:      # wire type 0
    return _pb_varint((field << 3) | 0) + _pb_varint(value)


def _pb_str(field: int, s: str) -> bytes:
    return _pb_len(field, s.encode())


def _gf_url(tfs_bytes: bytes) -> str:
    tfs = base64.urlsafe_b64encode(tfs_bytes).decode("ascii").rstrip("=")
    return ("https://www.google.com/travel/flights/search?tfs=" + tfs
            + "&curr=USD&hl=en&gl=US")


def google_flights_url(
    origin: str, dest: str, out_date: str, back_date: str, pax: int = 1,
    legs_out: list[dict] | None = None, legs_back: list[dict] | None = None,
) -> str:
    """A Google Flights deep link with the right party size.

    When `legs_out`/`legs_back` are given (each item a dict with `depart_airport`,
    `arrive_airport`, `depart_dt`, `carrier`, `flight_number`), the link encodes the
    *exact* flights the pipeline selected — the same itinerary a shared `/s/<token>`
    link points to. Otherwise it falls back to a route+dates+pax search.

    `pax` adults, economy. Round trip when `back_date` is set, else one-way.
    """
    def airport(code: str) -> bytes:       # Airport wrapper { f1=1, f2=code }
        return _pb_int(1, 1) + _pb_str(2, code)

    def slice_search(date: str, frm: str, to: str) -> bytes:
        body = (_pb_str(2, date)
                + _pb_len(13, airport(frm)) + _pb_len(14, airport(to)))
        return _pb_len(3, body)

    def segment(leg: dict) -> bytes:
        return _pb_len(4,
            _pb_str(1, leg["depart_airport"]) + _pb_str(2, str(leg["depart_dt"])[:10])
            + _pb_str(3, leg["arrive_airport"]) + _pb_str(5, leg["carrier"])
            + _pb_str(6, str(leg["flight_number"])))

    def slice_exact(legs: list[dict]) -> bytes:
        frm, to = legs[0]["depart_airport"], legs[-1]["arrive_airport"]
        date = str(legs[0]["depart_dt"])[:10]
        body = _pb_str(2, date) + b"".join(segment(x) for x in legs)
        body += _pb_len(13, airport(frm)) + _pb_len(14, airport(to))
        return _pb_len(3, body)

    if legs_out:
        data = slice_exact(legs_out)
        if legs_back:
            data += slice_exact(legs_back)
    else:
        data = slice_search(out_date, origin, dest)
        if back_date:
            data += slice_search(back_date, dest, origin)

    passengers = b"".join(_pb_int(8, 1) for _ in range(max(1, pax)))  # repeated ADULT
    info = _pb_int(1, 2) + _pb_int(2, 2) + data + passengers + _pb_int(9, 1)
    return _gf_url(info)


def hotel_booking_url(
    name: str, location: str, checkin: str, checkout: str, pax: int = 1, rooms: int = 1
) -> str:
    """A deep link to the exact suggested hotel with the plan's dates + party size.

    Uses Booking.com's documented, stable search params (`ss`, `checkin`, `checkout`,
    `group_adults`, `no_rooms`) — unlike Google Hotels, these reliably pre-fill the
    property, dates, and occupancy from a plain URL. Falls back to a location-only
    search when `name` is empty (e.g. a flat-rate estimate with no real property).
    """
    ss = f"{name}, {location}" if name else location
    params = {
        "ss": ss,
        "checkin": checkin[:10],
        "checkout": checkout[:10],
        "group_adults": max(1, pax),
        "no_rooms": max(1, rooms),
        "group_children": 0,
        "selected_currency": "USD",   # else Booking.com shows the viewer's locale currency
    }
    return "https://www.booking.com/searchresults.html?" + urlencode(params)


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].strip("-") or "trip"


def scenario_id(payload: str, n: int = 8) -> str:
    """Stable short hash for idempotent run identity from a canonical string."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:n]
