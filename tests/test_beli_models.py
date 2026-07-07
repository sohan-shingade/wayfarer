from wayfarer.models import BeliEntry, BeliSnapshot, TasteProfile, GroupTasteProfile


def test_snapshot_counts_computed_and_serialized():
    snap = BeliSnapshot(
        profile_name="alice",
        captured_at="2026-06-27T00:00:00",
        source="video",
        entries=[
            BeliEntry(name="Lhasa Fast Food", score=9.0, cuisine="Tibetan",
                      neighborhood="Jackson Heights", list_type="been"),
            BeliEntry(name="Phayul", cuisine="Tibetan", list_type="want_to_try"),
        ],
    )
    assert snap.counts == {"been": 1, "want_to_try": 1, "recs": 0}
    # computed field must survive JSON round-trip
    assert '"counts"' in snap.model_dump_json()


def test_entry_defaults_are_safe():
    e = BeliEntry(name="X")
    assert e.score is None and e.vibe == [] and e.list_type == "been"


def test_profile_and_group_construct():
    p = TasteProfile(profile_name="alice")
    assert p.cuisine_affinity == {} and p.dislikes == []
    g = GroupTasteProfile(members=["a", "b"])
    assert g.consensus_cuisines == []
