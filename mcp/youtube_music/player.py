from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus
import time
import re

VARIANT_TOKENS = [
    "live",
    "cover",
    "remix",
    "acoustic",
    "karaoke",
    "slowed",
    "sped up",
    "nightcore",
    "instrumental",
    "demo",
    "rehearsal",
    "tribute",
    "version",
]

ORIGINAL_MODIFIERS = ["la original", "original"]


def title_similarity(a: str, b: str) -> float:
    a = a.lower()
    b = b.lower()
    return 1.0 if a == b else (1.0 if a in b or b in a else 0.0)


def wants_original(query: str) -> bool:
    q = query.lower()
    return any(mod in q for mod in ORIGINAL_MODIFIERS)


def clean_music_query(query: str) -> str:
    cleaned = query.strip()
    for modifier in ORIGINAL_MODIFIERS:
        cleaned = re.sub(rf"\b{re.escape(modifier)}\b", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def is_variant_candidate(candidate: Dict[str, Any]) -> bool:
    haystack = " ".join(
        str(candidate.get(key, "")) for key in ("title", "artist", "album", "subtitle")
    ).lower()
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", haystack)
        for token in VARIANT_TOKENS
    )


def rank_music_candidates(query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Score candidates deterministically by simple heuristics.

    Candidates should be dicts with `title` and optional `artist` and `badges`.
    """
    original_requested = wants_original(query)
    q = clean_music_query(query).lower()

    ranked = []
    for c in candidates:
        title = c.get("title", "").lower()
        artist = c.get("artist", "").lower()
        score = 0.0
        # title match
        if q in title:
            score += 0.5
        elif any(w in title for w in q.split()):
            score += 0.2

        # artist match
        if artist and any(w in artist for w in q.split()):
            score += 0.3

        # official badge
        badges = c.get("badges", [])
        if "official" in [b.lower() for b in badges]:
            score += 0.15

        # penalize live/cover/remix
        if is_variant_candidate(c):
            score -= 1.0 if original_requested else 0.2

        c2 = dict(c)
        c2["score"] = round(score, 3)
        ranked.append(c2)

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


class YouTubeMusic:
    def __init__(self, browser, state: Optional[Any] = None):
        self.browser = browser
        self.state = state

    def _remember_search(self, query: str, candidates: List[Dict[str, Any]], index: int = 0):
        if not self.state:
            return
        self.state.set(
            "lastMusicSearch",
            {
                "query": query,
                "candidates": candidates,
                "current_index": index,
                "rejected": [],
            },
        )

    def _update_last_search_index(self, index: int, rejected: Optional[List[int]] = None):
        if not self.state:
            return
        last = self.state.get("lastMusicSearch", {})
        last["current_index"] = index
        if rejected is not None:
            last["rejected"] = rejected
        self.state.set("lastMusicSearch", last)

    def _player_bar(self):
        page = self.browser._page
        try:
            bar = page.locator("ytmusic-player-bar")
            return bar
        except Exception:
            return None

    def get_current_track(self) -> Dict[str, Any]:
        page = self.browser._page
        bar = self._player_bar()
        if not bar:
            return {"ok": False, "error": "player bar not found"}
        try:
            # heuristics for title and artist
            title = ""
            artist = ""
            try:
                title = bar.locator('yt-formatted-string.title').first.inner_text()
            except Exception:
                # fallback: any formatted string in bar
                try:
                    title = bar.locator('yt-formatted-string').nth(0).inner_text()
                except Exception:
                    title = ""
            try:
                artist = bar.locator('.byline a').first.inner_text()
            except Exception:
                try:
                    artist = bar.locator('yt-formatted-string').nth(1).inner_text()
                except Exception:
                    artist = ""
            return {"ok": True, "title": title, "artist": artist}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def pause(self) -> Dict[str, Any]:
        page = self.browser._page
        try:
            btn = page.get_by_role("button", name="Pause")
            btn.click()
            time.sleep(0.2)
            return {"ok": True}
        except Exception:
            # try player bar pause selector
            try:
                bar = self._player_bar()
                if bar:
                    bar.locator('tp-yt-paper-icon-button[title="Pause"]').click()
                    time.sleep(0.2)
                    return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def resume(self) -> Dict[str, Any]:
        page = self.browser._page
        try:
            btn = page.get_by_role("button", name="Play")
            btn.click()
            time.sleep(0.2)
            return {"ok": True}
        except Exception:
            try:
                bar = self._player_bar()
                if bar:
                    bar.locator('tp-yt-paper-icon-button[title="Play"]').click()
                    time.sleep(0.2)
                    return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def next(self) -> Dict[str, Any]:
        page = self.browser._page
        try:
            btn = page.get_by_role("button", name="Next")
            btn.click()
            time.sleep(0.3)
            return {"ok": True}
        except Exception:
            try:
                bar = self._player_bar()
                if bar:
                    bar.locator('tp-yt-paper-icon-button[title="Next"]').click()
                    time.sleep(0.3)
                    return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def previous(self) -> Dict[str, Any]:
        page = self.browser._page
        try:
            btn = page.get_by_role("button", name="Previous")
            btn.click()
            time.sleep(0.3)
            return {"ok": True}
        except Exception:
            try:
                bar = self._player_bar()
                if bar:
                    bar.locator('tp-yt-paper-icon-button[title="Previous"]').click()
                    time.sleep(0.3)
                    return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def get_queue(self) -> Dict[str, Any]:
        page = self.browser._page
        try:
            # try to open queue panel
            qbtn = page.get_by_role("button", name="Queue")
            qbtn.click()
            time.sleep(0.5)
            items = page.locator('ytmusic-queue-item-renderer')
            n = items.count()
            queue = []
            for i in range(min(n, 50)):
                try:
                    title = items.nth(i).locator('yt-formatted-string').first.inner_text()
                except Exception:
                    title = items.nth(i).inner_text()[:120]
                queue.append({"index": i, "title": title})
            return {"ok": True, "queue": queue}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def play(self, query_or_candidate: Any, max_tries: int = 3) -> Dict[str, Any]:
        """Play by query string or by candidate dict (as returned by search).

        Strategy: search -> rank -> try top candidates, verify via get_current_track.
        """
        page = self.browser._page
        candidates = []
        query = None
        if isinstance(query_or_candidate, str):
            query = query_or_candidate
            candidates = self.search(query_or_candidate)
            self._remember_search(query_or_candidate, candidates)
        elif isinstance(query_or_candidate, dict):
            candidates = [query_or_candidate]
        elif isinstance(query_or_candidate, list):
            candidates = query_or_candidate
        else:
            return {"ok": False, "error": "unsupported play argument"}

        if not candidates:
            return {"ok": False, "error": "no candidates found"}

        tries = 0
        for index, cand in enumerate(candidates):
            if tries >= max_tries:
                break
            tries += 1
            if self._play_candidate(cand):
                if query is not None:
                    self._update_last_search_index(index)
                return {"ok": True, "candidate": cand, "index": index}

        return {"ok": False, "error": "could not start playback"}

    def _play_candidate(self, cand: Dict[str, Any]) -> bool:
        page = self.browser._page
        try:
            items = page.locator("ytmusic-responsive-list-item-renderer")
            n = items.count()
            for i in range(n):
                el = items.nth(i)
                try:
                    t = el.locator('yt-formatted-string').first.inner_text()
                except Exception:
                    t = el.inner_text()[:120]
                if cand.get("title", "").lower() in t.lower():
                    try:
                        el.click()
                        time.sleep(0.6)
                        self.resume()
                        return self._verify_playback(cand)
                    except Exception:
                        pass

            try:
                items.nth(0).click()
                time.sleep(0.6)
                self.resume()
                return self._verify_playback(cand, strict=False)
            except Exception:
                return False
        except Exception:
            return False

    def _verify_playback(self, cand: Dict[str, Any], strict: bool = True) -> bool:
        info = self.get_current_track()
        if not info.get("ok"):
            return False
        if not strict:
            return bool(info.get("title") or info.get("artist"))
        expected = cand.get("title", "").lower()
        actual = info.get("title", "").lower()
        return bool(expected and (expected in actual or actual in expected))

    def reject_current_and_play_next(self, max_tries: int = 3) -> Dict[str, Any]:
        """Conversational flow for "esa no": skip rejected result and try the next one."""
        if not self.state:
            return {"ok": False, "error": "state is required for lastMusicSearch"}
        last = self.state.get("lastMusicSearch")
        if not last:
            return {"ok": False, "error": "no lastMusicSearch"}

        candidates = last.get("candidates") or []
        current_index = int(last.get("current_index", 0))
        rejected = list(last.get("rejected") or [])
        if current_index not in rejected:
            rejected.append(current_index)

        tries = 0
        for index in range(current_index + 1, len(candidates)):
            if index in rejected:
                continue
            if tries >= max_tries:
                break
            tries += 1
            candidate = candidates[index]
            if self._play_candidate(candidate):
                self._update_last_search_index(index, rejected)
                return {"ok": True, "candidate": candidate, "index": index, "rejected": rejected}

        self._update_last_search_index(current_index, rejected)
        return {"ok": False, "error": "no more candidates", "rejected": rejected}

    def esa_no(self, max_tries: int = 3) -> Dict[str, Any]:
        return self.reject_current_and_play_next(max_tries=max_tries)

    def search(self, query: str) -> List[Dict[str, Any]]:
        search_query = clean_music_query(query)
        url = f"https://music.youtube.com/search?q={quote_plus(search_query)}"
        self.browser.open(url)
        time.sleep(1)
        # try to extract candidates using common element hints
        page = self.browser._page
        candidates = []
        try:
            # generic selector likely to work: responsive list items
            items = page.locator("ytmusic-responsive-list-item-renderer")
            n = items.count()
            for i in range(min(n, 8)):
                el = items.nth(i)
                try:
                    title = el.locator('yt-formatted-string').first.inner_text()
                except Exception:
                    title = el.inner_text()[:100]
                artist = ""
                try:
                    artist = el.locator('.byline a').first.inner_text()
                except Exception:
                    pass
                badges = []
                candidates.append({"title": title, "artist": artist, "badges": badges})
        except Exception:
            # fallback: try text search for results
            # look for strings that look like titles
            pass

        return rank_music_candidates(query, candidates)
