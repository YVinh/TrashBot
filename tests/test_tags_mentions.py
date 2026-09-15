from tags_mentions import (
    format_hashtags,
    format_mentions,
    generate_hashtags,
    get_location_from_coords,
    get_mentions_for_location,
)


def test_get_location_from_coords_known_cities():
    assert get_location_from_coords(50.85, 4.35) == "Brussels"
    assert get_location_from_coords(52.37, 4.9) == "Amsterdam"
    assert get_location_from_coords(51.22, 4.4) == "Antwerp"


def test_get_location_from_coords_saint_josse_takes_priority_over_brussels():
    # Saint-Josse-ten-Noode is fully contained within the wider Brussels box,
    # so the narrower check must win.
    assert get_location_from_coords(50.853, 4.372) == "SaintJosse"


def test_get_location_from_coords_falls_back_to_europe():
    assert get_location_from_coords(48.85, 2.35) == "Europe"


def test_generate_hashtags_first_four_include_location_tags():
    # Regression test: location-specific tags used to be pushed past index 4,
    # so every caller's `hashtags[:4]` slice only ever saw universal tags.
    tags = generate_hashtags("Brussels")
    first_four = tags[:4]

    assert "#bruxellespropreté" in first_four
    # Brussels now has enough location-specific tags that #Bruxelles itself
    # sits past index 4 — just confirm it's still in the full list.
    assert "#Bruxelles" in tags
    assert any(tag in tags for tag in ("#ActionClimatique", "#AlerteDéchets"))


def test_generate_hashtags_saint_josse_includes_local_and_regional_tags():
    tags = generate_hashtags("SaintJosse")

    assert tags[0] == "#SaintJosseNews"
    assert "#Bruxelles" in tags
    assert any(tag in tags for tag in ("#ActionClimatique", "#AlerteDéchets"))


def test_generate_hashtags_unknown_location_falls_back_to_universal():
    tags = generate_hashtags("Nowhereville")
    assert tags[:4] == [
        "#ActionClimatique",
        "#AlerteDéchets",
        "#PropretéUrbaine",
        "#AgirPourLeClimat",
    ]


def test_generate_hashtags_contains_no_duplicates():
    tags = generate_hashtags("Amsterdam")
    assert len(tags) == len(set(tags))


def test_get_mentions_for_location_known_and_fallback():
    assert "BrusselsCity" in get_mentions_for_location("Brussels")
    assert get_mentions_for_location("Nowhereville") == get_mentions_for_location("Europe")


def test_format_hashtags_adds_missing_hash_prefix():
    assert format_hashtags(["Trash", "#ActionClimatique"]) == "#Trash #ActionClimatique"


def test_format_mentions_adds_at_prefix():
    assert format_mentions(["GreenpeaceBE", "WWF_BE"]) == "@GreenpeaceBE @WWF_BE"
