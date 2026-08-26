import json


def test_open_web_target_infers_url_and_remembers(tmp_path, monkeypatch):
    import core.web_shortcuts as web

    opened = []
    monkeypatch.setattr(web, "memory_dir", lambda: tmp_path / "memory")

    result = web.open_web_target("github", launcher=opened.append)
    second = web.open_web_target("github", launcher=opened.append)

    registry = json.loads((tmp_path / "memory" / "web_shortcuts.json").read_text(encoding="utf-8"))
    assert result["url"] == "https://github.com"
    assert second["source"] == "memory"
    assert opened == ["https://github.com", "https://github.com"]
    assert registry["aliases"]["github"]["timesOpened"] == 2


def test_search_google_builds_search_url():
    from core.web_shortcuts import search_google

    opened = []
    result = search_google("clima lima", launcher=opened.append)

    assert result["url"] == "https://www.google.com/search?q=clima+lima"
    assert opened == [result["url"]]


def test_remember_web_shortcut_adds_alias(tmp_path, monkeypatch):
    import core.web_shortcuts as web

    monkeypatch.setattr(web, "memory_dir", lambda: tmp_path / "memory")

    web.remember_web_shortcut("correo", "mail.google.com", label="Gmail")

    assert web.known_web_alias("correo") is True
    assert web.open_web_target("correo", launcher=lambda _url: None)["url"] == "https://mail.google.com"
