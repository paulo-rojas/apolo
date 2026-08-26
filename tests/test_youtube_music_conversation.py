from core.state import State
from mcp.youtube_music.player import (
    YouTubeMusic,
    candidate_from_block_text,
    clean_music_query,
    extract_candidates_from_visible_text,
    rank_music_candidates,
)


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


class SearchResultYouTubeMusic(YouTubeMusic):
    def __init__(self, candidates):
        super().__init__(FakeBrowser())
        self.candidates = candidates
        self.played = []

    def search(self, query, deadline=None):
        return self.candidates

    def _play_candidate(self, cand):
        self.played.append(cand)
        return True


class FakeCurrentTrackYouTubeMusic(YouTubeMusic):
    def __init__(self, info):
        super().__init__(FakeBrowser())
        self.info = info

    def get_current_track(self):
        return self.info


class EventuallyPlayingYouTubeMusic(YouTubeMusic):
    def __init__(self):
        super().__init__(FakeBrowser())
        self.calls = 0

    def _verify_playback(self, cand, strict=True):
        self.calls += 1
        return self.calls == 3


class FakeEvaluatePage:
    def __init__(self):
        self.received = None

    def evaluate(self, script, value):
        self.received = value
        return True


class FakeEvaluateBrowser:
    def __init__(self):
        self._page = FakeEvaluatePage()


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


def test_extract_candidates_from_visible_text():
    text = """
    Everlong
    Song • Foo Fighters • 767M plays
    Foo Fighters
    Artist • 20.9M monthly audience
    Everlong (Acoustic Version)
    Song • Foo Fighters • 50M plays
    """

    candidates = extract_candidates_from_visible_text(text)

    assert candidates == [
        {"title": "Everlong", "artist": "Foo Fighters", "badges": [], "kind": "song"},
        {
            "title": "Everlong (Acoustic Version)",
            "artist": "Foo Fighters",
            "badges": [],
            "kind": "song",
        },
    ]


def test_candidate_from_block_text():
    block = """
    Everlong
    Song • Foo Fighters • 767M plays
    """

    assert candidate_from_block_text(block) == {
        "title": "Everlong",
        "artist": "Foo Fighters",
        "badges": [],
        "kind": "song",
    }


def test_candidate_from_spanish_youtube_music_block_text():
    block = """
    Everlong
    Canción • Foo Fighters • 767 M reproducciones
    The Colour And The Shape
    """

    assert candidate_from_block_text(block) == {
        "title": "Everlong",
        "artist": "Foo Fighters",
        "badges": [],
        "kind": "song",
    }


def test_candidate_from_multiline_spanish_video_block_text():
    block = """
    Everlong (Official HD Video)
    Vídeo
    •
    Foo Fighters
    •
    390 M de visualizaciones
    """

    assert candidate_from_block_text(block) == {
        "title": "Everlong (Official HD Video)",
        "artist": "Foo Fighters",
        "badges": [],
        "kind": "video",
    }


def test_play_rejects_low_confidence_search_candidate(monkeypatch):
    monkeypatch.setenv("APOLO_MUSIC_MIN_AUTO_SCORE", "0.35")
    player = SearchResultYouTubeMusic(
        [{"title": "Barca, Barca, Barca", "artist": "Marcolinski", "score": 0.2}]
    )

    result = player.play("no de rinking barca")

    assert result["ok"] is False
    assert result["error"] == "low confidence music candidate"
    assert result["best_candidate"]["title"] == "Barca, Barca, Barca"
    assert player.played == []


def test_play_accepts_high_confidence_search_candidate(monkeypatch):
    monkeypatch.setenv("APOLO_MUSIC_MIN_AUTO_SCORE", "0.35")
    player = SearchResultYouTubeMusic(
        [{"title": "Numb", "artist": "Linkin Park", "score": 0.8}]
    )

    result = player.play("numb de linkin park")

    assert result["ok"] is True
    assert result["candidate"]["title"] == "Numb"
    assert player.played == [{"title": "Numb", "artist": "Linkin Park", "score": 0.8}]


def test_search_and_play_adults_are_talking_by_the_strokes(monkeypatch):
    monkeypatch.setenv("APOLO_MUSIC_MIN_AUTO_SCORE", "0.35")
    candidates = [
        {"title": "The Adults Are Talking", "artist": "The Strokes", "kind": "song", "score": 0.9},
        {"title": "The Adults Are Talking (Live)", "artist": "The Strokes", "kind": "video", "score": 0.4},
    ]
    player = SearchResultYouTubeMusic(candidates)

    result = player.play("the adults are talking de the strokes")

    assert result["ok"] is True
    assert result["candidate"]["title"] == "The Adults Are Talking"
    assert result["candidate"]["artist"] == "The Strokes"
    assert player.played[0]["title"] == "The Adults Are Talking"


def test_verify_playback_returns_bool_for_matching_track():
    player = FakeCurrentTrackYouTubeMusic({"ok": True, "title": "Everlong", "artist": "Foo Fighters"})

    assert player._verify_playback({"title": "Everlong"}) is True


def test_verify_playback_non_strict_still_rejects_unrelated_current_track():
    player = FakeCurrentTrackYouTubeMusic({"ok": True, "title": "Other Song", "artist": "Other"})

    assert player._verify_playback({"title": "Numb", "artist": "Linkin Park"}, strict=False) is False


def test_wait_for_playback_retries(monkeypatch):
    monkeypatch.setenv("APOLO_MUSIC_VERIFY_RETRIES", "3")
    monkeypatch.setenv("APOLO_MUSIC_VERIFY_DELAY_SECONDS", "0.1")
    player = EventuallyPlayingYouTubeMusic()

    assert player._wait_for_playback({"title": "Everlong"}) is True
    assert player.calls == 3


def test_click_player_button_accepts_localized_labels():
    browser = FakeEvaluateBrowser()
    player = YouTubeMusic(browser)

    assert player._click_player_button(["Pause", "Pausar"]) is True
    assert browser._page.received == ["Pause", "Pausar"]
