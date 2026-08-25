from core.state import State
from mcp.youtube_music.player import YouTubeMusic, clean_music_query, rank_music_candidates


class FakeBrowser:
    _page = None


class FakeYouTubeMusic(YouTubeMusic):
    def __init__(self, state, playable_titles):
        super().__init__(FakeBrowser(), state=state)
        self.playable_titles = set(playable_titles)
        self.played = []

    def _play_candidate(self, cand):
        self.played.append(cand["title"])
        return cand["title"] in self.playable_titles


def test_esa_no_rejects_current_and_plays_next(tmp_path):
    state = State(str(tmp_path / "state.db"))
    candidates = [
        {"title": "Song live", "artist": "Band"},
        {"title": "Song", "artist": "Band"},
        {"title": "Song remix", "artist": "Band"},
    ]
    state.set(
        "lastMusicSearch",
        {
            "query": "Song Band",
            "candidates": candidates,
            "current_index": 0,
            "rejected": [],
        },
    )
    player = FakeYouTubeMusic(state, playable_titles={"Song"})

    result = player.esa_no()

    assert result["ok"] is True
    assert result["candidate"]["title"] == "Song"
    assert result["index"] == 1
    assert state.get("lastMusicSearch")["current_index"] == 1
    assert state.get("lastMusicSearch")["rejected"] == [0]


def test_la_original_penalizes_common_variants():
    candidates = [
        {"title": "Song (Live)", "artist": "Band", "badges": ["Official"]},
        {"title": "Song", "artist": "Band", "badges": []},
        {"title": "Song remix", "artist": "Band", "badges": ["Official"]},
        {"title": "Song acoustic cover", "artist": "Other", "badges": []},
    ]

    ranked = rank_music_candidates("Song Band la original", candidates)

    assert ranked[0]["title"] == "Song"
    assert all("live" not in ranked[0]["title"].lower() for _ in [ranked[0]])
    assert ranked[0]["score"] > ranked[-1]["score"]


def test_clean_music_query_removes_original_modifier_case_insensitively():
    assert clean_music_query("Song Band LA ORIGINAL") == "Song Band"
