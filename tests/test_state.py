from core.state import State


def test_last_music_search_persists(tmp_path):
    db_path = tmp_path / "state.db"
    state = State(str(db_path))
    payload = {
        "query": "Everlong Foo Fighters",
        "current_index": 0,
        "candidates": [{"title": "Everlong", "artist": "Foo Fighters"}],
        "rejected": [],
    }

    state.set("lastMusicSearch", payload)

    fresh_state = State(str(db_path))
    assert fresh_state.get("lastMusicSearch") == payload
