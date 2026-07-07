"""Fast tier: pure deal-detection logic (relative tagging + absolute scoring)."""
from wayfarer.dealhunt import _month_dates, hunt
from wayfarer.engine.deals import score_deal, tag_deals
from wayfarer.models import Candidate, CoarseQuote


def _q(iata, price):
    return CoarseQuote(candidate=Candidate(city=iata, country="X", iata=iata),
                       cheapest_rt_total=price, out_date="2026-08-01", back_date="2026-08-08")


def test_tag_deals_flags_below_median():
    qs = [_q("A", 200), _q("B", 800), _q("C", 850), _q("D", 900)]
    tag_deals(qs, ratio=0.65)
    flagged = {q.candidate.iata: q.is_deal for q in qs}
    assert flagged["A"] is True       # 200 <= 0.65 * median(850)
    assert flagged["C"] is False


def test_tag_deals_noop_small_sample():
    qs = [_q("A", 100), _q("B", 900)]
    tag_deals(qs)
    assert all(q.is_deal is False for q in qs)


def test_score_deal_below_typical():
    v = score_deal(350, typical_low=700, typical_high=1200, price_level="low")
    assert v["is_deal"] is True
    assert v["discount_pct"] == 50.0


def test_score_deal_typical_not_a_deal():
    v = score_deal(900, typical_low=700, typical_high=1200, price_level="typical")
    assert v["is_deal"] is False
    assert v["discount_pct"] == 0.0


def test_month_dates():
    out, back = _month_dates("2026-10", 7)
    assert out == "2026-10-15" and back == "2026-10-22"


async def test_hunt_filters_and_sorts():
    class FakeProvider:
        async def price_insights(self, *, origin, dest, out_date, back_date, pax):
            data = {
                "HND": {"price": 350, "lowest_price": 350, "typical_low": 700, "typical_high": 1200, "price_level": "low"},
                "CDG": {"price": 600, "lowest_price": 600, "typical_low": 650, "typical_high": 1100, "price_level": "low"},
                "FCO": {"price": 900, "lowest_price": 900, "typical_low": 700, "typical_high": 1200, "price_level": "typical"},
            }
            return data.get(dest)

    targets = [("Tokyo", "", "Japan", "HND"), ("Paris", "", "France", "CDG"), ("Rome", "", "Italy", "FCO")]
    deals = await hunt(origins=["SFO"], month="2026-10", nights=7, pax=2,
                       provider=FakeProvider(), max_targets=10, min_discount=0.0, targets=targets)
    iatas = [d["iata"] for d in deals]
    assert iatas == ["HND", "CDG"]            # Rome (typical) excluded
    assert deals[0]["discount_pct"] > deals[1]["discount_pct"]  # sorted best-first
