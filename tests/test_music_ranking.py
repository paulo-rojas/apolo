from mcp.youtube_music.player import rank_music_candidates


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
