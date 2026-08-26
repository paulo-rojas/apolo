from mcp.youtube_music.player import rank_music_candidates, track_matches_candidate


def test_rank_simple():
    query = "Everlong Foo Fighters"
    candidates = [
        {"title": "Everlong", "artist": "Foo Fighters", "badges": ["Official"]},
        {"title": "Everlong (Live)", "artist": "Foo Fighters", "badges": []},
        {"title": "Everlong (Cover)", "artist": "Someone", "badges": []},
    ]
    ranked = rank_music_candidates(query, candidates)
    assert ranked[0]["artist"] == "Foo Fighters"
    assert ranked[0]["title"].lower().startswith("everlong")
    assert ranked[0]["score"] > ranked[1]["score"]


def test_track_verification_rejects_same_title_from_wrong_artist():
    candidate = {"title": "Numb", "artist": "Linkin Park"}

    assert track_matches_candidate(candidate, {"title": "Numb", "artist": "Other Artist"}) is False
    assert track_matches_candidate(candidate, {"title": "Numb", "artist": "Linkin Park"}) is True
