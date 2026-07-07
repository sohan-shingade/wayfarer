"""Fast tier: persistence/idempotency + budget-truth, all offline & deterministic."""
import json

from wayfarer.engine.budget import rebudget_from_exact
from wayfarer.models import (Brief, Budget, DayPlan, ExactFlight, ExactHotel, Plan)
from wayfarer.output import write_run
from wayfarer.text import scenario_id, slugify


def _brief():
    return Brief(pax=2, budget_total=2000, origin_iata="SFO", origins=["SFO", "OAK", "SJC"],
                 month="2026-08", nights=4, vibe=["insane landscapes"])


def _plan(dest="Denver, United States"):
    return Plan(
        destination=dest,
        flight=ExactFlight(legs_out=[], legs_back=[], price_total=396.0,
                           book_url="https://www.google.com/travel/flights?q=x"),
        hotel=ExactHotel(name="Test Inn", nightly_rate=75.0, nights=4, total=300.0,
                         lat=39.7, lng=-104.9),
        budget=Budget(flights=396, lodging=300, per_diem=640, buffer=133.6),
        itinerary=[DayPlan(day=1, title="Arrive", notes="land")],
        summary="A trip.", origin="SFO", out_date="2026-08-07", back_date="2026-08-11",
        status="ok",
    )


def test_rebudget_from_exact_uses_real_prices():
    b = rebudget_from_exact(flight_total=500, hotel_total=420, per_diem=640, buffer_pct=0.10)
    assert b.flights == 500 and b.lodging == 420 and b.per_diem == 640
    assert b.buffer == round((500 + 420 + 640) * 0.10, 2)
    assert b.total == round(500 + 420 + 640 + b.buffer, 2)


def test_slugify_and_scenario_id_stable():
    assert slugify("Denver, United States") == "denver-united-states"
    assert scenario_id("abc") == scenario_id("abc")
    assert scenario_id("abc") != scenario_id("abd")


def test_write_run_creates_files(tmp_path):
    run_dir = write_run([_plan()], _brief(), out_root=tmp_path)
    assert run_dir.exists()
    names = {p.name for p in run_dir.iterdir()}
    assert "run.json" in names and "summary.md" in names and "index.html" in names
    assert any(n.startswith("plan-01-") and n.endswith(".json") for n in names)
    assert any(n.startswith("plan-01-") and n.endswith(".md") for n in names)
    # viewer embeds the plan data + a map marker
    html = (run_dir / "index.html").read_text()
    assert "Denver" in html and "leaflet" in html.lower()


def test_write_run_idempotent_same_scenario(tmp_path):
    a = write_run([_plan()], _brief(), out_root=tmp_path)
    b = write_run([_plan()], _brief(), out_root=tmp_path)
    assert a == b  # same scenario -> same directory, not a duplicate
    assert sum(1 for _ in tmp_path.iterdir()) == 1


def test_write_run_clears_stale_plans(tmp_path):
    write_run([_plan("Denver, USA"), _plan("Boise, USA")], _brief(), out_root=tmp_path)
    run_dir = write_run([_plan("Denver, USA")], _brief(), out_root=tmp_path)
    plan_files = list(run_dir.glob("plan-*.json"))
    assert len(plan_files) == 1  # stale second plan removed on re-run


def test_run_json_has_brief(tmp_path):
    run_dir = write_run([_plan()], _brief(), out_root=tmp_path)
    data = json.loads((run_dir / "run.json").read_text())
    assert data["brief"]["budget_total"] == 2000
    assert data["plan_count"] == 1
