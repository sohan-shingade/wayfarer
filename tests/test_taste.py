from wayfarer.models import BeliEntry, BeliSnapshot
from wayfarer.engine.taste import dedup_entries, build_profile


def _snap():
    return BeliSnapshot(
        profile_name="alice", captured_at="2026-06-27", source="video",
        entries=[
            BeliEntry(name="Lhasa Fast Food", score=9.0, cuisine="Tibetan",
                      neighborhood="Jackson Heights", price="$", list_type="been"),
            BeliEntry(name="Phayul", score=8.5, cuisine="Tibetan",
                      neighborhood="Jackson Heights", price="$", list_type="been"),
            BeliEntry(name="Adda", score=8.0, cuisine="Indian",
                      neighborhood="Long Island City", price="$$", list_type="been"),
            BeliEntry(name="Ayada", score=6.0, cuisine="Thai",
                      neighborhood="Elmhurst", price="$$", list_type="been"),
            BeliEntry(name="Some Spot", score=4.0, cuisine="Colombian",
                      neighborhood="Jackson Heights", price="$", list_type="been"),
            BeliEntry(name="Raja's", cuisine="Indian", list_type="want_to_try"),
        ],
    )


def test_dedup_prefers_been_and_collapses_repeats():
    e1 = BeliEntry(name="Lhasa Fast Food", neighborhood="Jackson Heights",
                   list_type="want_to_try")
    e2 = BeliEntry(name="lhasa fast food ", score=9.0, neighborhood="Jackson Heights",
                   list_type="been")
    out = dedup_entries([e1, e2])
    assert len(out) == 1 and out[0].list_type == "been"


def test_build_profile_affinity_and_dislikes():
    p = build_profile(_snap(), generated_at="2026-06-27")
    # scores span lo=4.0 hi=9.0; Tibetan avg=8.75 -> norm=(8.75-4)/5=0.95
    assert p.cuisine_affinity["Tibetan"] == 0.95
    assert p.cuisine_affinity["Indian"] == 0.8
    assert p.cuisine_affinity["Thai"] == 0.4
    assert p.cuisine_affinity["Colombian"] == 0.0
    # top cuisine is Tibetan
    assert p.top_cuisines[0].cuisine == "Tibetan" and p.top_cuisines[0].n == 2
    # Colombian affinity < 0.25 -> dislike
    assert any(d.target == "Colombian" and d.kind == "cuisine" for d in p.dislikes)
    assert all(d.target != "Thai" for d in p.dislikes)
    # wishlist passthrough
    assert p.want_to_try == ["Raja's"]
    # score histogram floors
    assert p.score_distribution == {"9": 1, "8": 2, "6": 1, "4": 1}
    assert p.from_snapshot == "alice" and p.generated_at == "2026-06-27"


def test_build_profile_empty_been_does_not_crash():
    snap = BeliSnapshot(profile_name="x", entries=[
        BeliEntry(name="Wishlist Only", list_type="want_to_try")])
    p = build_profile(snap)
    assert p.cuisine_affinity == {} and p.want_to_try == ["Wishlist Only"]
