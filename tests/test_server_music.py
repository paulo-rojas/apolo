import asyncio

from mcp.browser.playwright_driver import BrowserCdpUnavailable, BrowserProfileInUse

from mcp.server import MusicProxy, collect_codex_context, error_response


class FakeBrowserProxy:
    def __init__(self):
        self._impl = object()
        self.ensured = False

    def _ensure(self):
        self.ensured = True


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


def test_browser_profile_in_use_error_omits_trace():
    result = error_response(BrowserProfileInUse("perfil ocupado"))

    assert result == {"ok": False, "error": "perfil ocupado"}


def test_browser_cdp_unavailable_error_omits_trace():
    result = error_response(BrowserCdpUnavailable("cdp apagado"))

    assert result == {"ok": False, "error": "cdp apagado"}


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
    monkeypatch.setattr(server, "browser", FakeBrowser())

    context = asyncio.run(collect_codex_context())

    assert context["lastCommand"] == "abre GitHub"
    assert "browserState" not in context
