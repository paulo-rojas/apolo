import asyncio
from contextlib import contextmanager
import time

import pytest

from mcp.browser.playwright_driver import BrowserCdpUnavailable, BrowserProfileInUse

pytest.importorskip("fastapi", reason="fastapi not installed; skipping server tests")

from mcp.server import MusicProxy, collect_codex_context, error_response, remember_codex_route


class FakeBrowserProxy:
    def __init__(self):
        self._impl = object()
        self.ensured = False

    def _ensure(self):
        self.ensured = True


class FakeTabbedBrowser:
    def __init__(self):
        self.used_tabs = []

    @contextmanager
    def using_tab(self, **kwargs):
        self.used_tabs.append(kwargs)
        yield object()

    def smart_click(self, target):
        return {"ok": True, "target": target}


class FakeTabbedBrowserProxy(FakeBrowserProxy):
    def __init__(self):
        self._impl = FakeTabbedBrowser()
        self.ensured = False


def test_browser_proxy_does_not_connect_until_a_tool_is_called(monkeypatch):
    import mcp.server as server

    created = []

    class FakeBrowser:
        def __init__(self):
            created.append(self)

        def _ensure_started(self):
            raise AssertionError("browser must not start during proxy construction")

    monkeypatch.setattr("mcp.browser.playwright_driver.PlaywrightBrowser", FakeBrowser)
    proxy = server.BrowserProxy()

    assert proxy._impl is None
    assert created == []


def test_music_proxy_accepts_query_alias(monkeypatch):
    class FakeState:
        pass

    class FakeYouTubeMusic:
        def __init__(self, browser, state=None):
            self.browser = browser
            self.state = state

        def play(self, query_or_candidate, max_tries=3):
            return {"query_or_candidate": query_or_candidate, "max_tries": max_tries}

    monkeypatch.setattr("core.state.State", FakeState)
    monkeypatch.setattr("mcp.youtube_music.player.YouTubeMusic", FakeYouTubeMusic)

    browser = FakeBrowserProxy()
    proxy = MusicProxy(browser)

    result = proxy.call("play", {"query": "Everlong", "max_tries": 2})

    assert browser.ensured is True
    assert result == {"query_or_candidate": "Everlong", "max_tries": 2}


def test_music_proxy_accepts_structured_music_entities(monkeypatch):
    class FakeState:
        pass

    class FakeYouTubeMusic:
        def __init__(self, browser, state=None):
            self.browser = browser
            self.state = state

        def play(self, query_or_candidate, max_tries=3):
            return {"query_or_candidate": query_or_candidate, "max_tries": max_tries}

    monkeypatch.setattr("core.state.State", FakeState)
    monkeypatch.setattr("mcp.youtube_music.player.YouTubeMusic", FakeYouTubeMusic)

    proxy = MusicProxy(FakeBrowserProxy())

    result = proxy.call(
        "play",
        {"query": "Numb", "artist": "Linkin Park", "platform": "youtube", "max_tries": 2},
    )

    assert result == {"query_or_candidate": "Numb Linkin Park", "max_tries": 2}


def test_music_proxy_runs_actions_in_youtube_music_tab(monkeypatch):
    class FakeState:
        pass

    class FakeYouTubeMusic:
        def __init__(self, browser, state=None):
            self.browser = browser
            self.state = state

        def next(self):
            return {"ok": True}

    monkeypatch.setattr("core.state.State", FakeState)
    monkeypatch.setattr("mcp.youtube_music.player.YouTubeMusic", FakeYouTubeMusic)

    browser = FakeTabbedBrowserProxy()
    proxy = MusicProxy(browser)

    result = proxy.call("next", {})

    assert result == {"ok": True}
    assert browser._impl.used_tabs == [
        {
            "url_contains": "music.youtube.com",
            "create_url": "https://music.youtube.com",
            "restore": True,
            "remember_key": "youtube_music",
        }
    ]


def test_browser_proxy_runs_actions_in_remembered_browser_tab():
    import mcp.server as server

    proxy = server.BrowserProxy()
    proxy._impl = FakeTabbedBrowser()

    result = proxy.call("smart_click", {"target": "Enviar"})

    assert result == {"ok": True, "target": "Enviar"}
    assert proxy._impl.used_tabs == [
        {
            "create_url": "about:blank",
            "restore": True,
            "remember_key": "browser",
        }
    ]


def test_browser_proxy_routes_dom_methods(monkeypatch):
    import mcp.server as server

    class FakeBrowser:
        def dom_click(self, target):
            return {"target": target}

    proxy = server.BrowserProxy()
    proxy._impl = FakeBrowser()

    assert proxy.call("dom_click", {"target": "Buscar"}) == {"target": "Buscar"}


def test_execute_tool_can_open_system_app(monkeypatch):
    import mcp.server as server

    monkeypatch.setattr("core.system_apps.open_system_app", lambda name: {"ok": True, "app": name})

    result = asyncio.run(server.execute_tool("system.open_app", {"name": "editor"}))

    assert result == {"ok": True, "app": "editor"}


def test_execute_tool_can_close_system_app(monkeypatch):
    import mcp.server as server

    monkeypatch.setattr("core.system_apps.close_system_app", lambda name: {"ok": True, "app": name, "closed": 1})

    result = asyncio.run(server.execute_tool("system.close_app", {"name": "editor"}))

    assert result == {"ok": True, "app": "editor", "closed": 1}


def test_execute_tool_can_set_system_volume(monkeypatch):
    import mcp.server as server

    monkeypatch.setattr(
        "core.system_volume.set_system_volume",
        lambda level=None, direction=None, step=5: {"ok": True, "level": level, "direction": direction, "step": step},
    )

    result = asyncio.run(server.execute_tool("system.set_volume", {"level": 50}))

    assert result == {"ok": True, "level": 50, "direction": None, "step": 5}


def test_execute_tool_uses_configured_volume_step(monkeypatch, tmp_path):
    import mcp.server as server

    config_path = tmp_path / "config.json"
    config_path.write_text('{"system":{"volume_step":7}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config_path))
    monkeypatch.setattr(
        "core.system_volume.set_system_volume",
        lambda level=None, direction=None, step=5: {"ok": True, "level": level, "direction": direction, "step": step},
    )

    result = asyncio.run(server.execute_tool("system.set_volume", {"direction": "down"}))

    assert result == {"ok": True, "level": None, "direction": "down", "step": 7}


def test_execute_tool_rejects_raw_voice_command_args():
    import mcp.server as server
    from core.tool_contract import ToolContractError

    with pytest.raises(ToolContractError):
        asyncio.run(server.execute_tool("youtube_music.play", {"query": "Apolo pon Numb de Linkin Park"}))


def test_music_tool_has_five_second_execution_timeout(monkeypatch, tmp_path):
    import mcp.server as server

    monkeypatch.setenv("APOLO_CONFIG_FILE", str(tmp_path / "missing-config.json"))

    async def slow_call(*args, **kwargs):
        await asyncio.sleep(6)

    monkeypatch.setattr(server, "run_agent_call", slow_call)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(server.execute_tool("youtube_music.pause", {}))


def test_agent_worker_ignores_late_result_after_timeout():
    import mcp.server as server

    worker = server.AgentWorker()
    loop_errors = []

    def slow_call():
        time.sleep(0.05)
        return {"ok": True}

    async def run_timeout():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(worker.call(slow_call), timeout=0.001)
        await asyncio.sleep(0.1)

    asyncio.run(run_timeout())

    assert loop_errors == []


def test_execute_tool_accepts_codex_app_arg_for_close_system_app(monkeypatch):
    import mcp.server as server

    monkeypatch.setattr("core.system_apps.close_system_app", lambda name: {"ok": True, "app": name, "closed": 1})

    result = asyncio.run(server.execute_tool("system.close_app", {"app": "discord"}))

    assert result == {"ok": True, "app": "discord", "closed": 1}


def test_handle_tool_path_speaks_when_system_app_is_missing(monkeypatch):
    import mcp.server as server
    from core.system_apps import SystemAppNotFound

    spoken = []

    async def fake_execute_tool(tool, args):
        raise SystemAppNotFound("No encontré una aplicación llamada de es corta")

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(server, "schedule_speech", spoken.append)

    parsed = {
        "kind": "mcp",
        "tool": "system.open_app",
        "args": {"name": "de es corta"},
    }
    result = asyncio.run(server.handle_tool_path("Apolo abre la aplicación de es corta", parsed))

    assert result["ok"] is True
    assert result["kind"] == "feedback"
    assert result["response"] == "No encontré la aplicación de es corta."
    assert result["result"]["ok"] is False
    assert "trace" not in result
    assert spoken == ["No encontré la aplicación de es corta."]


def test_handle_tool_path_speaks_when_system_app_is_not_open(monkeypatch):
    import mcp.server as server
    from core.system_apps import SystemAppNotFound

    spoken = []

    async def fake_execute_tool(tool, args):
        raise SystemAppNotFound("No encontré una aplicación abierta llamada discord")

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(server, "schedule_speech", spoken.append)

    parsed = {
        "kind": "mcp",
        "tool": "system.close_app",
        "args": {"name": "discord"},
    }
    result = asyncio.run(server.handle_tool_path("Apolo cierra la aplicación Discord", parsed))

    assert result["response"] == "No encontré abierta la aplicación discord."
    assert spoken == ["No encontré abierta la aplicación discord."]


def test_handle_tool_path_speaks_when_exact_volume_backend_is_missing(monkeypatch):
    import mcp.server as server
    from core.system_volume import SystemVolumeUnavailable

    spoken = []

    async def fake_execute_tool(tool, args):
        raise SystemVolumeUnavailable("exact volume requires nircmd.exe or a future Windows audio backend")

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(server, "schedule_speech", spoken.append)

    parsed = {
        "kind": "mcp",
        "tool": "system.set_volume",
        "args": {"level": 20},
    }
    result = asyncio.run(server.handle_tool_path("Apolo baja el volumen a 20", parsed))

    assert result["ok"] is True
    assert result["kind"] == "feedback"
    assert result["result"]["ok"] is False
    assert "trace" not in result
    assert result["response"] == "No puedo fijar un volumen exacto todavía. Puedo subirlo o bajarlo por pasos."
    assert spoken == ["No puedo fijar un volumen exacto todavía. Puedo subirlo o bajarlo por pasos."]


def test_handle_tool_path_speaks_when_goal_volume_verification_fails(monkeypatch):
    import mcp.server as server
    from core.system_volume import SystemVolumeUnavailable

    spoken = []

    async def fake_execute_tool(tool, args):
        raise SystemVolumeUnavailable("exact volume requires nircmd.exe or a future Windows audio backend")

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(server, "schedule_speech", spoken.append)

    parsed = {
        "kind": "mcp",
        "tool": "system.set_volume",
        "args": {"level": 20},
        "goal": {
            "objective": "bajar volumen a 20",
            "actions": [{"tool": "system.set_volume", "args": {"level": 20}}],
        },
    }
    result = asyncio.run(server.handle_tool_path("Apolo baja el volumen a 20", parsed))

    assert result["ok"] is True
    assert result["execution"]["verified"] is False
    assert result["feedback"] == "unavailable"
    assert result["response"] == "No puedo fijar un volumen exacto todavía. Puedo subirlo o bajarlo por pasos."
    assert spoken == ["No puedo fijar un volumen exacto todavía. Puedo subirlo o bajarlo por pasos."]


def test_handle_tool_path_executes_goal_and_records_observation(monkeypatch):
    import mcp.server as server

    async def fake_execute_tool(tool, args):
        return {"ok": True, "tool": tool, "args": args}

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)
    parsed = {
        "kind": "mcp",
        "tool": "youtube_music.pause",
        "args": {},
        "goal": {
            "objective": "pausa",
            "actions": [{"tool": "youtube_music.pause", "args": {}}],
        },
    }

    result = asyncio.run(server.handle_tool_path("Apolo pausa", parsed))

    assert result["result"] == {"ok": True, "tool": "youtube_music.pause", "args": {}}
    assert result["execution"]["verified"] is True
    assert result["execution"]["observations"][0]["ok"] is True


def test_execute_goal_marks_replan_when_verification_fails(monkeypatch):
    import mcp.server as server

    async def fake_execute_tool(tool, args):
        return {"ok": False, "error": "not playing"}

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)

    execution = asyncio.run(
        server.execute_goal(
            {
                "goal": {
                    "objective": "reanudar musica",
                    "actions": [{"tool": "youtube_music.resume", "args": {}}],
                }
            }
        )
    )

    assert execution["verified"] is False
    assert execution["replan_required"] is True
    assert execution["replan"] == "ask_or_escalate_on_failed_verification"
    assert execution["failure"]["type"] == "recoverable"


def test_execute_goal_runs_multistep_actions_in_order(monkeypatch):
    import mcp.server as server

    calls = []

    async def fake_execute_tool(tool, args):
        calls.append((tool, args))
        if tool == "web.open":
            return {"ok": True, "url": args["target"]}
        return {"ok": True, "tool": tool}

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)

    execution = asyncio.run(
        server.execute_goal(
            {
                "goal": {
                    "objective": "reproducir numb en youtube music",
                    "max_actions": 5,
                    "actions": [
                        {"tool": "browser.ensure_cdp", "args": {}, "verify": "tool_result_ok"},
                        {
                            "tool": "web.open",
                            "args": {"target": "https://music.youtube.com"},
                            "verify": "web_opened",
                        },
                        {"tool": "youtube_music.play", "args": {"query": "numb"}, "verify": "music_action_ok"},
                    ],
                }
            }
        )
    )

    assert calls == [
        ("browser.ensure_cdp", {}),
        ("web.open", {"target": "https://music.youtube.com"}),
        ("youtube_music.play", {"query": "numb"}),
    ]
    assert execution["verified"] is True
    assert len(execution["observations"]) == 3


def test_execute_goal_stops_when_intermediate_action_fails(monkeypatch):
    import mcp.server as server

    calls = []

    async def fake_execute_tool(tool, args):
        calls.append((tool, args))
        if tool == "web.open":
            return {"ok": True}
        return {"ok": True}

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)

    execution = asyncio.run(
        server.execute_goal(
            {
                "goal": {
                    "objective": "abrir youtube music y reproducir numb",
                    "actions": [
                        {"tool": "browser.ensure_cdp", "args": {}},
                        {"tool": "web.open", "args": {"target": "https://music.youtube.com"}, "verify": "web_opened"},
                        {"tool": "youtube_music.play", "args": {"query": "numb"}},
                    ],
                }
            }
        )
    )

    assert calls == [
        ("browser.ensure_cdp", {}),
        ("web.open", {"target": "https://music.youtube.com"}),
    ]
    assert execution["verified"] is False
    assert execution["replan_required"] is True
    assert execution["failure"] == {"type": "recoverable", "action": 1}


def test_execute_goal_can_resolve_args_from_previous_observation(monkeypatch):
    import mcp.server as server

    calls = []

    async def fake_execute_tool(tool, args):
        calls.append((tool, args))
        if tool == "web.open":
            return {"ok": True, "url": "https://music.youtube.com"}
        return {"ok": True, "target": args["target"]}

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)

    execution = asyncio.run(
        server.execute_goal(
            {
                "goal": {
                    "objective": "abrir y verificar pagina",
                    "actions": [
                        {"tool": "web.open", "args": {"target": "https://music.youtube.com"}, "verify": "web_opened"},
                        {
                            "tool": "browser.find",
                            "args": {"target": {"from_observation": {"index": 0, "path": "result.url"}}},
                        },
                    ],
                }
            }
        )
    )

    assert calls == [
        ("web.open", {"target": "https://music.youtube.com"}),
        ("browser.find", {"target": "https://music.youtube.com"}),
    ]
    assert execution["verified"] is True


def test_execute_goal_refuses_plans_over_max_actions(monkeypatch):
    import mcp.server as server

    async def fake_execute_tool(tool, args):
        raise AssertionError("oversized plans must not execute")

    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)

    execution = asyncio.run(
        server.execute_goal(
            {
                "goal": {
                    "objective": "plan demasiado largo",
                    "max_actions": 1,
                    "actions": [
                        {"tool": "browser.ensure_cdp", "args": {}},
                        {"tool": "youtube_music.play", "args": {"query": "numb"}},
                    ],
                }
            }
        )
    )

    assert execution["verified"] is False
    assert execution["replan_required"] is False
    assert execution["failure"] == {"type": "definitive", "action": None}
    assert execution["result"] == {"ok": False, "error": "goal exceeds max_actions"}


def test_execute_tool_can_open_web(monkeypatch):
    import mcp.server as server

    monkeypatch.setattr("core.web_shortcuts.open_web_target", lambda target: {"ok": True, "url": target})

    result = asyncio.run(server.execute_tool("web.open", {"target": "github"}))

    assert result == {"ok": True, "url": "github"}


def test_execute_tool_can_search_google(monkeypatch):
    import mcp.server as server

    monkeypatch.setattr("core.web_shortcuts.search_google", lambda query: {"ok": True, "query": query})

    result = asyncio.run(server.execute_tool("web.search_google", {"query": "clima lima"}))

    assert result == {"ok": True, "query": "clima lima"}


def test_execute_tool_can_ensure_browser_cdp(monkeypatch):
    import mcp.server as server

    calls = []
    ensured = []

    def fake_ensure_cdp(close_existing=False):
        calls.append(close_existing)
        return {"ok": True, "status": "already_available"}

    class FakeBrowser:
        def _ensure(self):
            ensured.append(True)

    monkeypatch.setattr("mcp.browser.cdp_manager.ensure_cdp", fake_ensure_cdp)
    monkeypatch.setattr(server, "browser", FakeBrowser())

    result = asyncio.run(server.execute_tool("browser.ensure_cdp", {}))

    assert result == {"ok": True, "status": "already_available"}
    assert calls == [False]
    assert ensured == [True]


def test_browser_profile_in_use_error_omits_trace():
    result = error_response(BrowserProfileInUse("perfil ocupado"))

    assert result == {"ok": False, "error": "perfil ocupado"}


def test_browser_cdp_unavailable_error_omits_trace():
    result = error_response(BrowserCdpUnavailable("cdp apagado"))

    assert result == {"ok": False, "error": "cdp apagado"}


def test_timeout_error_omits_trace():
    result = error_response(TimeoutError())

    assert result == {"ok": False, "error": "tool timed out"}


def test_collect_codex_context_does_not_start_browser(monkeypatch):
    import mcp.server as server

    class FakeState:
        def __init__(self):
            self.values = {
                "lastTranscript": "Apolo abre GitHub",
                "lastCommand": "abre GitHub",
                "voiceSession": {"active": True},
                "lastMusicSearch": None,
            }

        def get(self, key):
            return self.values.get(key)

    class FakeBrowser:
        def snapshot_state(self):
            return None

        def call(self, method, args):
            raise AssertionError("collect_codex_context must not call browser tools")

    monkeypatch.setattr("core.state.State", FakeState)
    monkeypatch.setattr("core.memory_files.read_memory_context", lambda: {"profile": ""})
    monkeypatch.setattr(server, "browser", FakeBrowser())

    context = asyncio.run(collect_codex_context())

    assert context["lastCommand"] == "abre GitHub"
    assert "browserState" not in context


def test_remember_codex_route_tracks_repeated_commands(tmp_path):
    from core.state import State

    state = State(str(tmp_path / "state.db"))

    remember_codex_route(
        state,
        "dime la hora actual",
        {"parsed": {"kind": "answer", "text": "Son las 3:04 p. m."}},
        12000,
    )
    remember_codex_route(
        state,
        "dime la hora actual",
        {"parsed": {"kind": "answer", "text": "Son las 3:05 p. m."}},
        11000,
    )

    learned = state.get("learnedCodexRoutes")
    assert learned["dime la hora actual"]["count"] == 2
    assert learned["dime la hora actual"]["lastElapsedMs"] == 11000


def test_execute_tool_can_write_memory(tmp_path, monkeypatch):
    import mcp.server as server

    monkeypatch.setenv("APOLO_CONFIG_FILE", str(tmp_path / "missing-config.json"))
    monkeypatch.setattr("core.memory_files.memory_dir", lambda: tmp_path / "memory")

    result = asyncio.run(
        server.execute_tool("memory.remember", {"text": "usar respuestas breves", "source": "test"})
    )

    assert result["text"] == "usar respuestas breves"
    assert (tmp_path / "memory" / "apolo_profile.md").exists()


def test_execute_tool_blocks_memory_when_disabled(tmp_path, monkeypatch):
    import mcp.server as server

    config_path = tmp_path / "config.json"
    config_path.write_text('{"memory":{"allow_codex_write":false}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config_path))

    with pytest.raises(Exception) as exc:
        asyncio.run(server.execute_tool("memory.remember", {"text": "no guardar"}))

    assert getattr(exc.value, "status_code", None) == 403


def test_handle_codex_path_uses_cached_repetitive_answer(tmp_path, monkeypatch):
    import mcp.server as server

    monkeypatch.setenv("APOLO_CONFIG_FILE", str(tmp_path / "missing-config.json"))
    monkeypatch.setattr("core.memory_files.memory_dir", lambda: tmp_path / "memory")

    from core.memory_files import maybe_remember_repetitive_answer

    maybe_remember_repetitive_answer(
        "define protocolo tls",
        {"parsed": {"kind": "answer", "text": "TLS cifra la comunicacion."}},
        {"count": 2},
    )

    async def fake_speak(text):
        return None

    monkeypatch.setattr(server, "speak_response", fake_speak)

    result = asyncio.run(
        server.handle_codex_path(
            "Apolo define protocolo TLS",
            {"kind": "codex", "command": "define protocolo tls"},
        )
    )

    assert result["response"] == "TLS cifra la comunicacion."
    assert result["memory"]["kind"] == "repetitive_answer"
    assert "codex" not in result


def test_handle_codex_path_speaks_when_codex_does_not_understand(monkeypatch):
    import mcp.server as server

    spoken = []

    class FakeBridge:
        def run(self, command, context):
            return {"parsed": {"kind": "ignore", "reason": "unclear"}, "raw": "{}"}

    async def fake_collect_context():
        return {}

    monkeypatch.setattr("core.codex_bridge.CodexBridge", FakeBridge)
    monkeypatch.setattr(server, "collect_codex_context", fake_collect_context)
    monkeypatch.setattr(server, "schedule_speech", spoken.append)

    result = asyncio.run(
        server.handle_codex_path(
            "Apolo blorpea el tablero azul",
            {
                "kind": "codex",
                "command": "blorpea el tablero azul",
                "reason": "local parser did not understand command",
            },
        )
    )

    assert result["response"] == "No entendí la instrucción."
    assert spoken == ["Voy a consultarlo con Codex.", "No entendí la instrucción."]


def test_handle_codex_path_announces_handoff_before_call(monkeypatch):
    import mcp.server as server

    spoken = []
    calls = []

    class FakeBridge:
        def run(self, command, context):
            calls.append(("run", list(spoken)))
            return {"parsed": {"kind": "answer", "text": "Respuesta lista."}, "raw": "{}"}

    async def fake_collect_context():
        return {}

    monkeypatch.setattr("core.codex_bridge.CodexBridge", FakeBridge)
    monkeypatch.setattr("core.memory_files.cached_repetitive_answer", lambda command: {})
    monkeypatch.setattr(server, "collect_codex_context", fake_collect_context)
    monkeypatch.setattr(server, "schedule_speech", spoken.append)

    result = asyncio.run(
        server.handle_codex_path(
            "Apolo explica arquitectura lunar",
            {"kind": "codex", "command": "explica arquitectura lunar"},
        )
    )

    assert calls == [("run", ["Voy a consultarlo con Codex."])]
    assert result["response"] == "Respuesta lista."
    assert spoken == ["Voy a consultarlo con Codex.", "Respuesta lista."]


def test_handle_codex_path_speaks_when_auto_tool_has_empty_app_name(monkeypatch):
    import mcp.server as server
    from core.system_apps import SystemAppNotFound

    spoken = []

    class FakeBridge:
        def run(self, command, context):
            return {
                "parsed": {"kind": "mcp", "tool": "system.open_app", "args": {}},
                "raw": "{}",
            }

    async def fake_collect_context():
        return {}

    async def fake_execute_tool(tool, args):
        raise SystemAppNotFound("app name is empty")

    monkeypatch.setattr("core.codex_bridge.CodexBridge", FakeBridge)
    monkeypatch.setattr("core.codex_bridge.codex_auto_execute_tools", lambda: True)
    monkeypatch.setattr(server, "collect_codex_context", fake_collect_context)
    monkeypatch.setattr(server, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(server, "schedule_speech", spoken.append)

    result = asyncio.run(
        server.handle_codex_path(
            "Apolo Sierra Discord",
            {"kind": "codex", "command": "Sierra Discord"},
        )
    )

    assert result["response"] == "No entendí qué aplicación quieres abrir."
    assert result["result"] == {"ok": False, "error": "app name is empty"}
    assert spoken == ["Voy a consultarlo con Codex.", "No entendí qué aplicación quieres abrir."]


def test_handle_local_rest_sets_listener_rest_flag(tmp_path, monkeypatch):
    import core.listener_control as control
    import mcp.server as server

    monkeypatch.setattr(control, "_REST_PATH", tmp_path / "rest.flag")

    async def fake_speak(text):
        return None

    monkeypatch.setattr(server, "schedule_speech", lambda text: None)

    result = asyncio.run(
        server.handle_local_path("Apolo descansa", {"kind": "local", "command": "rest"})
    )

    assert result["response"] == "Nos vemos luego"
    assert control.listener_is_resting() is True


def test_handle_local_shutdown_sets_shutdown_flag(tmp_path, monkeypatch):
    import core.listener_control as control
    import mcp.server as server

    monkeypatch.setattr(control, "_SHUTDOWN_PATH", tmp_path / "shutdown.flag")
    monkeypatch.setattr(server, "schedule_speech", lambda text: None)

    result = asyncio.run(
        server.handle_local_path("Apolo termina la sesión", {"kind": "local", "command": "shutdown"})
    )

    assert result["response"] == "Nos vemos luego"
    assert control.shutdown_requested() is True
