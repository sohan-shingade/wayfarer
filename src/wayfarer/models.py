"""The data contracts that flow stage to stage. These are the spine of the system;
each pipeline stage consumes one of these and produces the next.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field


class Brief(BaseModel):
    """Stage 0 output: the structured request the brainstormer/engine work from."""
    pax: int = 2
    budget_total: float
    origin_iata: str                 # primary origin (display + default)
    origins: list[str] = Field(default_factory=list)  # all airports to price; empty -> [origin_iata]
    month: str                       # e.g. "2026-08"
    nights: int = 7
    flexible_dates: bool = True
    vibe: list[str] = Field(default_factory=list)   # e.g. ["dramatic landscapes", "hiking"]
    long_haul_ok: bool = True
    hard_ceiling: bool = True        # is budget_total a wall or a target?


class Candidate(BaseModel):
    """Stage 1 output: one brainstormed destination, no prices yet."""
    city: str
    country: str
    region: str = ""                 # state/province, to disambiguate hotel search
    iata: str                        # primary arrival airport
    vibe_score: float = 0.0          # 0..1, how well it matches Brief.vibe
    in_season: bool = True           # is the month good there?
    rationale: str = ""              # why the brainstormer picked it (for the critic/logs)


class CoarseQuote(BaseModel):
    """Stage 2: cheapest round-trip estimate found in the month for a candidate."""
    candidate: Candidate
    cheapest_rt_total: float         # for the whole party
    out_date: str
    back_date: str
    origin: str = ""                 # winning origin airport (cheapest of brief.origins)
    is_deal: bool = False            # standout-cheap fare within this run (relative)


class Budget(BaseModel):
    flights: float
    lodging: float
    per_diem: float
    buffer: float

    @computed_field  # serialized in model_dump/JSON so the viewer + saved files have it
    @property
    def total(self) -> float:
        return round(self.flights + self.lodging + self.per_diem + self.buffer, 2)


class PricedCandidate(BaseModel):
    """Stage 3 output: a candidate with a full assembled budget."""
    quote: CoarseQuote
    budget: Budget
    rank_score: float = 0.0


class FlightLeg(BaseModel):
    carrier: str
    flight_number: str
    depart_airport: str
    arrive_airport: str
    depart_dt: str
    arrive_dt: str


class ExactFlight(BaseModel):
    legs_out: list[FlightLeg]
    legs_back: list[FlightLeg]
    price_total: float               # party total
    book_url: str = ""


class ExactHotel(BaseModel):
    name: str
    nightly_rate: float
    nights: int
    total: float
    book_url: str = ""
    lat: float | None = None         # from SerpApi gps_coordinates, for the map view
    lng: float | None = None


class Stop(BaseModel):
    """One mappable activity on a day: a named place with coordinates. Drives the
    per-candidate activity viewer (a route walked stop-by-stop on a map)."""
    name: str
    lat: float
    lng: float
    note: str = ""                   # what you do there
    start: str = ""                  # rough local start time, e.g. "9:00 AM" (display only)
    end: str = ""                    # rough local end time, e.g. "11:00 AM"


class DayPlan(BaseModel):
    day: int
    title: str
    notes: str                       # landscape-focused activity ideas, prose
    stops: list[Stop] = Field(default_factory=list)  # geocoded activities for the map


class Plan(BaseModel):
    """Stage 4 output: one finished, presentable trip plan."""
    destination: str
    flight: ExactFlight
    hotel: ExactHotel
    budget: Budget
    itinerary: list[DayPlan]
    summary: str
    origin: str = ""                 # winning origin airport (display)
    out_date: str = ""               # robust dates even when flight legs are empty
    back_date: str = ""
    is_deal: bool = False            # standout-cheap fare for this run
    status: Literal["ok", "over_budget", "flagged"] = "ok"
    critic_notes: str = ""


# ---------------------------------------------------------------------------
# Beli taste-profile contracts (sub-project A). Snapshot = raw export;
# TasteProfile = derived; GroupTasteProfile = N people merged.
# ---------------------------------------------------------------------------
class BeliEntry(BaseModel):
    """One restaurant as read off a Beli screen (perception output)."""
    name: str
    score: float | None = None           # Beli /10
    rank: int | None = None              # position in their list, if visible
    cuisine: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    price: str | None = None             # "$".."$$$$"
    vibe: list[str] = Field(default_factory=list)
    list_type: Literal["been", "want_to_try", "recs"] = "been"
    notes: str | None = None
    source_shot: str = ""                # frame/file provenance


class BeliSnapshot(BaseModel):
    """\"Your Beli data, exported.\" The stable seam: path B writes this too."""
    profile_name: str
    captured_at: str = ""
    source: Literal["screenshots", "video", "api"] = "video"
    username: str | None = None
    entries: list[BeliEntry] = Field(default_factory=list)

    @computed_field
    @property
    def counts(self) -> dict[str, int]:
        out = {"been": 0, "want_to_try": 0, "recs": 0}
        for e in self.entries:
            out[e.list_type] = out.get(e.list_type, 0) + 1
        return out


class CuisineAffinity(BaseModel):
    cuisine: str
    affinity: float                      # 0..1
    n: int
    avg_score: float | None = None


class NeighborhoodPref(BaseModel):
    area: str
    n: int
    avg_score: float | None = None


class Dislike(BaseModel):
    target: str
    kind: Literal["cuisine", "spot"]
    reason: Literal["low_score", "low_rank"]


class TasteProfile(BaseModel):
    """Derived per-person taste signal a planner consumes."""
    profile_name: str
    cuisine_affinity: dict[str, float] = Field(default_factory=dict)
    top_cuisines: list[CuisineAffinity] = Field(default_factory=list)
    favorite_neighborhoods: list[NeighborhoodPref] = Field(default_factory=list)
    price_tendency: dict = Field(default_factory=dict)   # {median_tier, distribution}
    vibe_tags: list[str] = Field(default_factory=list)
    dislikes: list[Dislike] = Field(default_factory=list)
    want_to_try: list[str] = Field(default_factory=list)
    score_distribution: dict[str, int] = Field(default_factory=dict)
    generated_at: str = ""
    from_snapshot: str = ""


class GroupCuisine(BaseModel):
    cuisine: str
    affinity: float


class GroupWant(BaseModel):
    name: str
    wanted_by: int


class GroupTasteProfile(BaseModel):
    """N people merged, for group crawls."""
    members: list[str] = Field(default_factory=list)
    consensus_cuisines: list[GroupCuisine] = Field(default_factory=list)
    popular_cuisines: list[GroupCuisine] = Field(default_factory=list)
    combined_dislikes: list[Dislike] = Field(default_factory=list)
    combined_want_to_try: list[GroupWant] = Field(default_factory=list)
    shared_neighborhoods: list[str] = Field(default_factory=list)
