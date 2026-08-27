from core.state import State
from voice.command_router import ActionPlanner, normalize_command, route_command
from voice.interpretation import DeterministicIntentResolver, IntentRegistry, IntentSpec, InterpretedCommand


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
    single_word = route_command("de Queen").as_dict()

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {"query": "", "artist": "los angeles azules"}
    assert result["interpretation"]["intent"] == "play_music"
    assert result["interpretation"]["entities"]["artist"] == "los angeles azules"
    assert result["interpretation"]["semantic_tree"]["children"][0]["children"] == [
        {"role": "artist", "text": "los angeles azules"}
    ]
    assert single_word["tool"] == "youtube_music.play"
    assert single_word["args"] == {"query": "", "artist": "queen"}


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


def test_non_music_intents_also_expose_a_semantic_tree():
    result = route_command("busca hoteles en Lima").as_dict()

    assert result["interpretation"]["semantic_tree"] == {
        "role": "web_search",
        "text": "busca hoteles en lima",
        "children": [{"role": "query", "text": "hoteles en lima"}],
    }


def test_restart_song_routes_to_youtube_music():
    result = route_command("reinicia la cancion").as_dict()

    assert result["tool"] == "youtube_music.restart"
    assert result["interpretation"]["intent"] == "restart_track"


def test_registered_future_domain_becomes_a_structured_action():
    planner = ActionPlanner(IntentRegistry([IntentSpec("send_email", ("to", "body"), tool_handler="mail.send")]))
    interpreted = InterpretedCommand(
        "manda un correo a ana",
        "manda un correo a ana",
        "send_email",
        {"to": "ana", "body": "hola"},
        0.95,
    )

    plan = planner.plan(interpreted)

    assert plan is not None
    assert plan.tool == "mail.send"
    assert plan.args == {"to": "ana", "body": "hola"}
    assert interpreted.semantic_tree.as_dict()["children"] == [
        {"role": "to", "text": "ana"},
        {"role": "body", "text": "hola"},
    ]


def test_registered_future_domain_can_be_planned_as_goal():
    planner = ActionPlanner(IntentRegistry([IntentSpec("send_email", ("to", "body"), tool_handler="mail.send")]))
    interpreted = InterpretedCommand(
        "manda un correo a ana",
        "manda un correo a ana",
        "send_email",
        {"to": "ana", "body": "hola"},
        0.95,
    )

    goal = planner.plan_goal(interpreted)

    assert goal is not None
    assert goal.as_dict() == {
        "intent": "send_email",
        "objective": "manda un correo a ana",
        "actions": [
            {
                "intent": "send_email",
                "tool": "mail.send",
                "args": {"to": "ana", "body": "hola"},
                "reason": "registered intent",
                "verify": "tool_result_ok",
                "observe": "tool_result",
            }
        ],
        "observe": "tool_result",
        "verify": "all_actions_ok",
        "replan": "ask_or_escalate_on_failed_verification",
        "max_actions": 5,
        "max_replans": 1,
    }


def test_mcp_routes_expose_goal_with_action_plan():
    result = route_command("pausa").as_dict()

    assert result["goal"]["objective"] == "pausa"
    assert result["goal"]["actions"] == [
        {
            "intent": "pause_music",
            "tool": "youtube_music.pause",
            "args": {},
            "reason": "routed intent",
            "verify": "tool_result_ok",
            "observe": "tool_result",
        }
    ]


def test_short_asr_variants_use_fuzzy_intent_matching():
    continua = route_command("contin a").as_dict()
    siguiente = route_command("siguiente accion").as_dict()

    assert continua["tool"] == "youtube_music.resume"
    assert continua["interpretation"]["source"] == "asr_fuzzy"
    assert siguiente["tool"] == "youtube_music.next"
    assert siguiente["interpretation"]["source"] == "asr_fuzzy"


def test_short_alias_matching_comes_from_intent_registry():
    registry = IntentRegistry(
        [
            IntentSpec(
                "mute_music",
                tool_handler="youtube_music.mute",
                voice_aliases=(("silencio", 0.97),),
            )
        ]
    )
    resolver = DeterministicIntentResolver(registry)

    exact = resolver.interpret("silencio", "silencio")
    fuzzy = resolver.interpret("silensio", "silensio")

    assert exact.intent == "mute_music"
    assert exact.source == "alias"
    assert fuzzy.intent == "mute_music"
    assert fuzzy.normalized_text == "silencio"
    assert fuzzy.source == "asr_fuzzy"


def test_fuzzy_matching_rejects_long_or_ambiguous_phrases():
    long_phrase = route_command("continua revisando la implementacion antes de tocar youtube").as_dict()
    negated = route_command("no pausa").as_dict()
    ambiguous = route_command("otra anterior").as_dict()

    assert long_phrase["tool"] == ""
    assert long_phrase["kind"] in {"codex", "ignore"}
    assert negated["tool"] == ""
    assert negated["kind"] in {"codex", "ignore"}
    assert ambiguous["tool"] == ""
    assert ambiguous["kind"] in {"codex", "ignore"}


def test_open_youtube_music_and_play_builds_multistep_goal():
    result = route_command("abre YouTube Music y pon Numb de Linkin Park").as_dict()

    assert result["kind"] == "mcp"
    assert result["tool"] == "youtube_music.play"
    assert result["args"] == {"query": "numb", "artist": "linkin park"}
    assert result["interpretation"]["intent"] == "open_and_play_music"
    assert result["goal"]["objective"] == "reproducir numb linkin park en YouTube Music"
    assert result["goal"]["actions"] == [
        {
            "intent": "open_and_play_music",
            "tool": "browser.ensure_cdp",
            "args": {},
            "reason": "prepare browser session",
            "verify": "tool_result_ok",
            "observe": "tool_result",
        },
        {
            "intent": "open_and_play_music",
            "tool": "web.open",
            "args": {"target": "https://music.youtube.com"},
            "reason": "open youtube music",
            "verify": "web_opened",
            "observe": "tool_result",
        },
        {
            "intent": "play_music",
            "tool": "youtube_music.play",
            "args": {"query": "numb", "artist": "linkin park"},
            "reason": "play requested media",
            "verify": "music_action_ok",
            "observe": "tool_result",
        },
    ]


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


def test_start_browser_routes_to_cdp_ensure():
    result = route_command("inicia navegador").as_dict()
    open_result = route_command("abre el navegador").as_dict()

    assert result["tool"] == "browser.ensure_cdp"
    assert result["args"] == {}
    assert open_result["tool"] == "browser.ensure_cdp"
    assert open_result["args"] == {}


def test_volume_intent_resolves_without_arbitrary_tool_execution():
    volume = route_command("sube el volumen").as_dict()
    level = route_command("sube el volumen a 50").as_dict()
    spoken_level = route_command("baja el volumen a treinta").as_dict()

    assert volume["kind"] == "mcp"
    assert volume["tool"] == "system.set_volume"
    assert volume["interpretation"]["intent"] == "set_volume"
    assert volume["interpretation"]["entities"] == {"direction": "up"}
    assert level["kind"] == "mcp"
    assert level["tool"] == "system.set_volume"
    assert level["interpretation"]["entities"] == {"level": 50}
    assert spoken_level["kind"] == "mcp"
    assert spoken_level["tool"] == "system.set_volume"
    assert spoken_level["interpretation"]["entities"] == {"level": 30}


def test_same_artist_uses_temporary_context(tmp_path):
    state = State(str(tmp_path / "state.db"))

    first = route_command("pon Numb de Linkin Park", state=state).as_dict()
    followup = route_command("pon otra del mismo grupo", state=state).as_dict()

    assert first["interpretation"]["entities"]["artist"] == "linkin park"
    assert followup["tool"] == "youtube_music.play"
    assert followup["interpretation"]["source"] == "context"
    assert followup["interpretation"]["entities"]["artist"] == "linkin park"


def test_context_keeps_the_last_structured_command_for_any_domain(tmp_path):
    state = State(str(tmp_path / "state.db"))

    route_command("busca hoteles en Lima", state=state)

    context = state.get("conversationContext")
    assert context["lastIntent"] == "web_search"
    assert context["lastCommand"]["entities"] == {"query": "hoteles en lima"}
    assert context["lastCommand"]["semanticTree"]["role"] == "web_search"


def test_ambiguous_inputs_do_not_execute_arbitrary_tools():
    phrases = ["pon eso", "haz lo de ayer", "busca eso que te dije", "abre"]

    for phrase in phrases:
        result = route_command(phrase).as_dict()

        assert result["kind"] in {"codex", "session", "ignore"}
        assert result["tool"] == ""
