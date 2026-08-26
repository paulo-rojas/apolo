from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus
import time
import re
import os
import unicodedata

from core.config import get_float, get_int

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


def _env_int(name: str, default: int) -> int:
    paths = {
        "APOLO_MUSIC_ACTION_TIMEOUT_SECONDS": "music.action_timeout_seconds",
        "APOLO_MUSIC_SEARCH_TIMEOUT_SECONDS": "music.search_timeout_seconds",
        "APOLO_MUSIC_VERIFY_RETRIES": "music.verify_retries",
    }
    return get_int(paths.get(name, name), default, env=name, minimum=1)


def _env_float(name: str, default: float) -> float:
    paths = {"APOLO_MUSIC_VERIFY_DELAY_SECONDS": "music.verify_delay_seconds"}
    return get_float(paths.get(name, name), default, env=name, minimum=0.1)


def _min_auto_score() -> float:
    return get_float(
        "music.min_auto_score",
        0.35,
        env="APOLO_MUSIC_MIN_AUTO_SCORE",
        minimum=0.0,
    )


def _candidate_score(candidate: Dict[str, Any]) -> Optional[float]:
    try:
        return float(candidate.get("score"))
    except (TypeError, ValueError):
        return None


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


def normalize_kind(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.strip().lower()


def canonical_kind(value: str) -> Optional[str]:
    normalized = normalize_kind(value)
    if normalized in {"song", "cancion"}:
        return "song"
    if normalized in {"video", "vid eo"}:
        return "video"
    return None


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


def extract_candidates_from_visible_text(text: str, limit: int = 8) -> List[Dict[str, Any]]:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and line.strip() != "•"
    ]
    candidates = []
    for index, line in enumerate(lines[:-1]):
        meta = lines[index + 1]
        parts = [part.strip() for part in meta.split("•")]
        if not parts:
            continue
        kind = canonical_kind(parts[0])
        if not kind:
            continue
        artist = parts[1] if len(parts) > 1 else ""
        if not artist and index + 2 < len(lines):
            next_line = lines[index + 2]
            if not canonical_kind(next_line) and "reproducciones" not in next_line.lower():
                artist = next_line
        candidates.append({"title": line, "artist": artist, "badges": [], "kind": kind})
        if len(candidates) >= limit:
            break
    return candidates


def candidate_from_block_text(text: str) -> Optional[Dict[str, Any]]:
    candidates = extract_candidates_from_visible_text(text, limit=1)
    if candidates:
        return candidates[0]
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and line.strip() != "•"
    ]
    if len(lines) < 2:
        return None
    title = lines[0]
    for meta_index, meta in enumerate(lines[1:], start=1):
        parts = [part.strip() for part in re.split(r"\s*•\s*", meta) if part.strip()]
        if not parts:
            continue
        kind = canonical_kind(parts[0])
        if not kind:
            continue
        artist = parts[1] if len(parts) > 1 else ""
        if not artist and meta_index + 1 < len(lines):
            next_line = lines[meta_index + 1]
            if not canonical_kind(next_line) and "reproducciones" not in next_line.lower():
                artist = next_line
        return {"title": title, "artist": artist, "badges": [], "kind": kind}
    return None


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
        try:
            info = page.evaluate(
                """
                () => {
                    const bar = document.querySelector('ytmusic-player-bar');
                    if (!bar) return {ok: false, error: 'player bar not found'};
                    const text = (selector) => {
                        const node = bar.querySelector(selector);
                        return node ? (node.innerText || node.textContent || '').trim() : '';
                    };
                    const title = text('yt-formatted-string.title') || text('.title');
                    const artist = text('.byline a') || text('.byline') || '';
                    return {ok: true, title, artist};
                }
                """
            )
            if info:
                return info
        except Exception:
            pass
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
        if self._click_player_button(["Pause", "Pausar"]):
            time.sleep(0.2)
            return {"ok": True}
        try:
            btn = page.get_by_role("button", name=re.compile("Pause|Pausar", re.I))
            btn.click(timeout=1000)
            time.sleep(0.2)
            return {"ok": True}
        except Exception:
            # try player bar pause selector
            try:
                bar = self._player_bar()
                if bar:
                    bar.locator(
                        'tp-yt-paper-icon-button[title="Pause"], '
                        'tp-yt-paper-icon-button[title="Pausar"]'
                    ).click(timeout=1000)
                    time.sleep(0.2)
                    return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {"ok": False, "error": "pause button not found"}

    def resume(self) -> Dict[str, Any]:
        page = self.browser._page
        if self._click_player_button(["Play", "Reproducir"]):
            time.sleep(0.2)
            return {"ok": True}
        try:
            btn = page.get_by_role("button", name=re.compile("Play|Reproducir", re.I))
            btn.click(timeout=1000)
            time.sleep(0.2)
            return {"ok": True}
        except Exception:
            try:
                bar = self._player_bar()
                if bar:
                    bar.locator(
                        'tp-yt-paper-icon-button[title="Play"], '
                        'tp-yt-paper-icon-button[title="Reproducir"]'
                    ).click(timeout=1000)
                    time.sleep(0.2)
                    return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {"ok": False, "error": "play button not found"}

    def next(self) -> Dict[str, Any]:
        page = self.browser._page
        if self._click_player_button(["Next", "Siguiente"]):
            time.sleep(0.3)
            return {"ok": True}
        try:
            btn = page.get_by_role("button", name=re.compile("Next|Siguiente", re.I))
            btn.click()
            time.sleep(0.3)
            return {"ok": True}
        except Exception:
            try:
                bar = self._player_bar()
                if bar:
                    bar.locator(
                        'tp-yt-paper-icon-button[title="Next"], '
                        'tp-yt-paper-icon-button[title="Siguiente"]'
                    ).click(timeout=1000)
                    time.sleep(0.3)
                    return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {"ok": False, "error": "next button not found"}

    def previous(self) -> Dict[str, Any]:
        page = self.browser._page
        if self._click_player_button(["Previous", "Anterior"]):
            time.sleep(0.3)
            return {"ok": True}
        try:
            btn = page.get_by_role("button", name=re.compile("Previous|Anterior", re.I))
            btn.click()
            time.sleep(0.3)
            return {"ok": True}
        except Exception:
            try:
                bar = self._player_bar()
                if bar:
                    bar.locator(
                        'tp-yt-paper-icon-button[title="Previous"], '
                        'tp-yt-paper-icon-button[title="Anterior"]'
                    ).click(timeout=1000)
                    time.sleep(0.3)
                    return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}
            return {"ok": False, "error": "previous button not found"}

    def _click_player_button(self, label: Any) -> bool:
        try:
            labels = label if isinstance(label, list) else [label]
            return bool(
                self.browser._page.evaluate(
                    """
                    (labels) => {
                        const bar = document.querySelector('ytmusic-player-bar') || document;
                        const needles = labels.map((label) => label.toLowerCase());
                        const nodes = Array.from(
                            bar.querySelectorAll('button, tp-yt-paper-icon-button, yt-icon-button')
                        );
                        const node = nodes.find((el) => {
                            const value = [
                                el.getAttribute('aria-label'),
                                el.getAttribute('title'),
                                el.innerText,
                                el.textContent
                            ].filter(Boolean).join(' ').toLowerCase();
                            return needles.some((needle) => value.includes(needle));
                        });
                        if (!node) return false;
                        node.click();
                        return true;
                    }
                    """,
                    labels,
                )
            )
        except Exception:
            return False

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
        deadline = time.monotonic() + _env_int("APOLO_MUSIC_ACTION_TIMEOUT_SECONDS", 20)
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

        indexed_candidates = list(enumerate(candidates))
        if query is not None:
            min_score = _min_auto_score()
            indexed_candidates = [
                (index, cand)
                for index, cand in indexed_candidates
                if (_candidate_score(cand) is None or _candidate_score(cand) >= min_score)
            ]
            if not indexed_candidates:
                return {
                    "ok": False,
                    "error": "low confidence music candidate",
                    "query": query,
                    "min_score": min_score,
                    "best_candidate": candidates[0],
                }

        tries = 0
        for index, cand in indexed_candidates:
            if time.monotonic() >= deadline:
                return {"ok": False, "error": "music action timeout"}
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
        if self._click_visible_play_button(cand.get("title", "")):
            time.sleep(0.8)
            return self._wait_for_playback(cand)

        if self._click_candidate_by_text(cand.get("title", "")):
            time.sleep(0.6)
            self.resume()
            return self._wait_for_playback(cand)

        try:
            items = page.locator("ytmusic-responsive-list-item-renderer")
            n = items.count()
            for i in range(n):
                el = items.nth(i)
                try:
                    t = el.locator('yt-formatted-string').first.inner_text(timeout=1000)
                except Exception:
                    try:
                        t = el.inner_text(timeout=1000)[:120]
                    except Exception:
                        t = ""
                if cand.get("title", "").lower() in t.lower():
                    try:
                        el.click(timeout=1000)
                        time.sleep(0.6)
                        self.resume()
                        return self._wait_for_playback(cand)
                    except Exception:
                        pass

            try:
                title = cand.get("title", "")
                if not title:
                    return False
                page.get_by_text(title, exact=True).first.click(timeout=3000)
                time.sleep(0.6)
                self.resume()
                return self._wait_for_playback(cand)
            except Exception:
                return False
        except Exception:
            try:
                title = cand.get("title", "")
                if not title:
                    return False
                page.get_by_text(title, exact=True).first.click(timeout=3000)
                time.sleep(0.6)
                self.resume()
                return self._wait_for_playback(cand)
            except Exception:
                return False

    def _wait_for_playback(self, cand: Dict[str, Any], strict: bool = True) -> bool:
        retries = _env_int("APOLO_MUSIC_VERIFY_RETRIES", 5)
        delay = _env_float("APOLO_MUSIC_VERIFY_DELAY_SECONDS", 0.7)
        for _ in range(retries):
            if self._verify_playback(cand, strict=strict):
                return True
            time.sleep(delay)
        return False

    def _verify_playback(self, cand: Dict[str, Any], strict: bool = True) -> bool:
        info = self.get_current_track()
        if not info.get("ok"):
            return False
        expected_title = cand.get("title", "").lower()
        expected_artist = cand.get("artist", "").lower()
        actual_title = info.get("title", "").lower()
        actual_artist = info.get("artist", "").lower()
        if not strict:
            title_matches = bool(
                expected_title and actual_title and (
                    expected_title in actual_title or actual_title in expected_title
                )
            )
            artist_matches = bool(
                expected_artist and actual_artist and (
                    expected_artist in actual_artist or actual_artist in expected_artist
                )
            )
            return title_matches or artist_matches
        return bool(
            expected_title
            and actual_title
            and (expected_title in actual_title or actual_title in expected_title)
        )

    def _click_visible_play_button(self, title: str) -> bool:
        page = self.browser._page
        try:
            if title:
                card = page.locator("ytmusic-card-shelf-renderer").filter(has_text=title).first
                card.get_by_role("button", name=re.compile("Play|Reproducir", re.I)).first.click(
                    timeout=2000
                )
                return True
        except Exception:
            pass

        try:
            page.get_by_role("button", name=re.compile("Play|Reproducir", re.I)).first.click(
                timeout=2000
            )
            return True
        except Exception:
            return False

    def _click_candidate_by_text(self, title: str) -> bool:
        if not title:
            return False
        try:
            return bool(
                self.browser._page.evaluate(
                    """
                    (title) => {
                        const selectors = [
                            'ytmusic-responsive-list-item-renderer',
                            'ytmusic-card-shelf-renderer',
                            'ytmusic-two-row-item-renderer',
                            'a',
                            'button'
                        ];
                        const nodes = selectors.flatMap((selector) =>
                            Array.from(document.querySelectorAll(selector))
                        );
                        const needle = title.toLowerCase();
                        const node = nodes.find((el) =>
                            (el.innerText || el.textContent || '').toLowerCase().includes(needle)
                        );
                        if (!node) return false;
                        const container = node.closest(
                            'ytmusic-responsive-list-item-renderer, ytmusic-card-shelf-renderer, ytmusic-two-row-item-renderer'
                        ) || node;
                        const playButton = Array.from(
                            container.querySelectorAll('button, tp-yt-paper-icon-button, yt-icon-button')
                        ).find((el) => {
                            const value = [
                                el.getAttribute('aria-label'),
                                el.getAttribute('title'),
                                el.innerText,
                                el.textContent
                            ].filter(Boolean).join(' ').toLowerCase();
                            return value.includes('play') || value.includes('reproducir');
                        });
                        if (playButton) {
                            playButton.click();
                            return true;
                        }
                        container.dispatchEvent(new MouseEvent('dblclick', {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        }));
                        container.click();
                        return true;
                    }
                    """,
                    title,
                )
            )
        except Exception:
            return False

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
        deadline = time.monotonic() + _env_int("APOLO_MUSIC_ACTION_TIMEOUT_SECONDS", 20)
        if current_index not in rejected:
            rejected.append(current_index)

        tries = 0
        for index in range(current_index + 1, len(candidates)):
            if time.monotonic() >= deadline:
                self._update_last_search_index(current_index, rejected)
                return {"ok": False, "error": "music action timeout", "rejected": rejected}
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

    def play_last_search_index(self, index: int, max_tries: int = 3) -> Dict[str, Any]:
        if not self.state:
            return {"ok": False, "error": "state is required for lastMusicSearch"}
        last = self.state.get("lastMusicSearch")
        if not last:
            return {"ok": False, "error": "no lastMusicSearch"}

        candidates = last.get("candidates") or []
        if index < 0 or index >= len(candidates):
            return {"ok": False, "error": "candidate index out of range"}

        if self._play_candidate(candidates[index]):
            rejected = list(last.get("rejected") or [])
            self._update_last_search_index(index, rejected)
            return {"ok": True, "candidate": candidates[index], "index": index}
        return {"ok": False, "error": "could not start playback", "index": index}

    def search(self, query: str) -> List[Dict[str, Any]]:
        timeout_seconds = _env_int("APOLO_MUSIC_SEARCH_TIMEOUT_SECONDS", 12)
        search_query = clean_music_query(query)
        url = f"https://music.youtube.com/search?q={quote_plus(search_query)}"
        self.browser.open(url, timeout=timeout_seconds, wait_until="domcontentloaded")
        # try to extract candidates using common element hints
        page = self.browser._page
        candidates = []
        try:
            block_texts = page.evaluate(
                """
                () => {
                    const selectors = [
                        'ytmusic-responsive-list-item-renderer',
                        'ytmusic-card-shelf-renderer',
                        'ytmusic-two-row-item-renderer'
                    ];
                    return selectors
                        .flatMap((selector) => Array.from(document.querySelectorAll(selector)))
                        .map((el) => el.innerText || el.textContent || '')
                        .filter((text) => text.trim())
                        .slice(0, 24);
                }
                """
            )
            for block_text in block_texts:
                candidate = candidate_from_block_text(block_text)
                if candidate:
                    candidates.append(candidate)
                if len(candidates) >= 8:
                    break
        except Exception:
            # fallback: try text search for results
            # look for strings that look like titles
            pass

        if not candidates:
            try:
                body_text = page.locator("body").inner_text(timeout=3000)
                candidates = extract_candidates_from_visible_text(body_text)
            except Exception:
                candidates = []

        return rank_music_candidates(query, candidates)
