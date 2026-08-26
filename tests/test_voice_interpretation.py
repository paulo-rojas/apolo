from core.state import State
from voice.command_router import normalize_command, route_command


def test_music_variants_converge_to_play_music():
    phrases = [
        "pon Numb",
        "ponme Numb",
        "quiero escuchar Numb",
        "reproduce Numb",
        "eh... pon Numb",
        "pon pon Numb",
        "apolo este... quiero escuchar Numb",
    ]

    for phrase in phrases:
        result = route_command(phrase).as_dict()

        assert result["kind"] == "mcp"
        assert result["tool"] == "youtube_music.play"
        assert result["interpretation"]["intent"] == "play_music"
        assert result["interpretation"]["entities"]["query"] == "numb"
        assert result["interpretation"]["confidence"] >= 0.85
        assert result["interpretation"]["needs_memory"] is False
        assert result["interpretation"]["needs_reasoning"] is False


def test_music_artist_is_extracted_but_tool_remains_compatible():
    result = route_command("reproduce Numb de Linkin Park").as_dict()

    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {"query": "numb", "artist": "linkin park"}
    assert result["interpretation"]["entities"] == {
        "query": "numb",
        "artist": "linkin park",
    }


def test_music_platform_is_extracted_from_en_youtube():
    result = route_command("pon Numb de Linkin Park en YouTube").as_dict()

    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {
        "query": "numb",
        "artist": "linkin park",
        "platform": "youtube",
    }
    assert result["interpretation"]["entities"] == {
        "query": "numb",
        "artist": "linkin park",
        "platform": "youtube",
    }
    assert result["interpretation"]["semantic_tree"] == {
        "role": "play_music",
        "text": "numb de linkin park",
        "children": [
            {
                "role": "media_query",
                "children": [
                    {"role": "query", "text": "numb"},
                    {"role": "artist", "text": "linkin park"},
                ],
            },
            {"role": "platform", "text": "youtube"},
        ],
    }


def test_de_prefix_is_artist_for_music_intent():
    result = route_command("de Los Angeles Azules").as_dict()

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {"query": "", "artist": "los angeles azules"}
    assert result["interpretation"]["intent"] == "play_music"
    assert result["interpretation"]["entities"]["artist"] == "los angeles azules"
    assert result["interpretation"]["semantic_tree"]["children"][0]["children"] == [
        {"role": "artist", "text": "los angeles azules"}
    ]


def test_de_artist_with_platform_is_structured():
    result = route_command("de Los Angeles Azules en YouTube").as_dict()

    assert result["args"] == {
        "query": "",
        "artist": "los angeles azules",
        "platform": "youtube",
    }


def test_music_reverse_artist_phrase_is_extracted():
    result = route_command("reproduce la de Linkin Park, Numb").as_dict()

    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {"query": "numb", "artist": "linkin park"}


def test_disfluencies_are_normalized_conservatively():
    assert normalize_command("apolo ehh... pon... ponme Numb") == "ponme numb"
    assert normalize_command("busca The Who") == "busca the who"


def test_web_search_variants_route_to_google():
    plain = route_command("busca hoteles en Lima").as_dict()
    repeated = route_command("busca busca hoteles en Lima").as_dict()

    assert plain["tool"] == "web.search_google"
    assert plain["args"] == {"query": "hoteles en lima"}
    assert repeated["tool"] == "web.search_google"
    assert repeated["args"] == {"query": "hoteles en lima"}


def test_application_open_and_correction():
    chrome = route_command("abre Chrome").as_dict()
    firefox = route_command("abre... no, abre Firefox").as_dict()

    assert chrome["tool"] == "web.open"
    assert chrome["args"] == {"target": "chrome"}
    assert firefox["tool"] == "web.open"
    assert firefox["args"] == {"target": "firefox"}


def test_close_discord_transcription_error_stays_local():
    result = route_command("cero a discolto").as_dict()

    assert result["kind"] == "mcp"
    assert result["tool"] == "system.close_app"
    assert result["args"] == {"name": "discord"}
    assert result["interpretation"]["needs_reasoning"] is False


def test_volume_intent_resolves_without_arbitrary_tool_execution():
    volume = route_command("sube el volumen").as_dict()
    level = route_command("sube el volumen a 50").as_dict()

    assert volume["kind"] == "mcp"
    assert volume["tool"] == "system.set_volume"
    assert volume["interpretation"]["intent"] == "set_volume"
    assert volume["interpretation"]["entities"] == {"direction": "up"}
    assert level["kind"] == "mcp"
    assert level["tool"] == "system.set_volume"
    assert level["interpretation"]["entities"] == {"level": 50}


def test_same_artist_uses_temporary_context(tmp_path):
    state = State(str(tmp_path / "state.db"))

    first = route_command("pon Numb de Linkin Park", state=state).as_dict()
    followup = route_command("pon otra del mismo grupo", state=state).as_dict()

    assert first["interpretation"]["entities"]["artist"] == "linkin park"
    assert followup["tool"] == "youtube_music.play"
    assert followup["interpretation"]["source"] == "context"
    assert followup["interpretation"]["entities"]["artist"] == "linkin park"


def test_ambiguous_inputs_do_not_execute_arbitrary_tools():
    phrases = ["pon eso", "haz lo de ayer", "busca eso que te dije", "abre"]

    for phrase in phrases:
        result = route_command(phrase).as_dict()

        assert result["kind"] in {"codex", "session", "ignore"}
        assert result["tool"] == ""
