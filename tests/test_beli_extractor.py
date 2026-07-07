from wayfarer.agents.beli_extractor import entries_from_rows


def test_entries_from_rows_coerces_and_sets_list_type():
    rows = [
        {"name": "Lhasa Fast Food", "score": 9.0, "cuisine": "Tibetan",
         "neighborhood": "Jackson Heights", "price": "$", "bogus_key": 1},
        {"name": "Phayul"},  # sparse row tolerated
    ]
    out = entries_from_rows(rows, list_type="been", source_shot="frame_0001.png")
    assert len(out) == 2
    assert out[0].name == "Lhasa Fast Food" and out[0].score == 9.0
    assert out[0].list_type == "been" and out[0].source_shot == "frame_0001.png"
    assert out[1].score is None and out[1].cuisine is None


def test_entries_from_rows_skips_nameless():
    out = entries_from_rows([{"score": 8.0}, {"name": "  "}], list_type="been")
    assert out == []
