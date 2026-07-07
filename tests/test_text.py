from wayfarer.text import place_query


def test_strips_parenthetical_landmark():
    assert place_query("Denver (Rocky Mountain NP)", "United States") == "Denver, United States"
    assert place_query("Salt Lake City (Canyonlands)", "United States") == "Salt Lake City, United States"


def test_plain_city_unchanged():
    assert place_query("Reykjavik", "Iceland") == "Reykjavik, Iceland"


def test_region_disambiguates():
    assert place_query("Jackson", "United States", "Wyoming") == "Jackson, Wyoming, United States"
    # parenthetical still stripped, region still added
    assert place_query("Denver (RMNP)", "United States", "Colorado") == "Denver, Colorado, United States"


def test_handles_missing_country():
    assert place_query("Bergen", "") == "Bergen"
