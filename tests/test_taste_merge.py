from wayfarer.models import BeliEntry, BeliSnapshot
from wayfarer.engine.taste import build_profile, merge_profiles


def _person(name, rows):
    return build_profile(BeliSnapshot(profile_name=name, entries=[
        BeliEntry(**r) for r in rows]))


def test_merge_consensus_popular_dislikes_wishlist():
    a = _person("a", [
        {"name": "T1", "score": 9.0, "cuisine": "Tibetan",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "I1", "score": 7.0, "cuisine": "Indian",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "C1", "score": 4.0, "cuisine": "Colombian",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "Raja's", "cuisine": "Indian", "list_type": "want_to_try"},
    ])
    b = _person("b", [
        {"name": "T2", "score": 8.0, "cuisine": "Tibetan",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "M2", "score": 9.0, "cuisine": "Mexican",
         "neighborhood": "Corona", "list_type": "been"},
        {"name": "C2", "score": 5.0, "cuisine": "Colombian",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "Raja's", "cuisine": "Indian", "list_type": "want_to_try"},
    ])
    g = merge_profiles([a, b])
    assert g.members == ["a", "b"]
    # Tibetan + Colombian are in BOTH -> consensus; Tibetan ranks first
    cons = {c.cuisine for c in g.consensus_cuisines}
    assert cons == {"Tibetan", "Colombian"}
    assert g.consensus_cuisines[0].cuisine == "Tibetan"
    # popular includes union (Indian, Mexican present in one each)
    pop = {c.cuisine for c in g.popular_cuisines}
    assert {"Tibetan", "Indian", "Mexican", "Colombian"} <= pop
    # both wanted Raja's -> wanted_by 2
    assert g.combined_want_to_try[0].name == "Raja's"
    assert g.combined_want_to_try[0].wanted_by == 2
    # Jackson Heights is a favorite for both -> shared
    assert "Jackson Heights" in g.shared_neighborhoods
    # Colombian is a dislike for both (low affinity) -> appears once
    targets = [(d.target, d.kind) for d in g.combined_dislikes]
    assert targets.count(("Colombian", "cuisine")) == 1

    # --- numeric precision: consensus uses MIN, popular uses MEAN ---
    # a: Tibetan=1.0, b: Tibetan=0.75  ->  consensus=min=0.75, popular_mean=0.875
    cons_tib = next(c for c in g.consensus_cuisines if c.cuisine == "Tibetan")
    assert cons_tib.affinity == 0.75, (
        f"consensus Tibetan must be min(1.0, 0.75)=0.75, got {cons_tib.affinity}"
    )
    pop_tib = next(c for c in g.popular_cuisines if c.cuisine == "Tibetan")
    assert pop_tib.affinity == 0.875, (
        f"popular Tibetan must be mean(1.0, 0.75)=0.875, got {pop_tib.affinity}"
    )
    # Mexican only in b -> popular affinity equals b's affinity (1.0)
    pop_mex = next(c for c in g.popular_cuisines if c.cuisine == "Mexican")
    assert pop_mex.affinity == 1.0, (
        f"popular Mexican (single member) must be 1.0, got {pop_mex.affinity}"
    )
