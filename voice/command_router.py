import re
from dataclasses import dataclass
from typing import Any, Dict

from .normalize import normalize_text


@dataclass
class RouteResult:
    kind: str
    command: str
    tool: str = ""
    args: Dict[str, Any] = None
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "command": self.command,
            "tool": self.tool,
            "args": self.args or {},
            "reason": self.reason,
        }


def route_command(command: str) -> RouteResult:
    normalized = normalize_text(command)
    if not normalized:
        return RouteResult(kind="ignore", command=command, reason="empty command")

    incomplete_music_verbs = {
        "pon",
        "ponme",
        "reproduce",
        "reproducir",
        "toca",
        "busca",
        "buscar",
        "quiero escuchar",
    }
    if normalized in incomplete_music_verbs:
        return RouteResult(kind="session", command=normalized, reason="missing command target")

    fast_path = {
        "pausa": ("youtube_music.pause", {}),
        "pausar": ("youtube_music.pause", {}),
        "pause": ("youtube_music.pause", {}),
        "reanuda": ("youtube_music.resume", {}),
        "continua": ("youtube_music.resume", {}),
        "continuar": ("youtube_music.resume", {}),
        "resume": ("youtube_music.resume", {}),
        "siguiente": ("youtube_music.next", {}),
        "next": ("youtube_music.next", {}),
        "anterior": ("youtube_music.previous", {}),
        "previous": ("youtube_music.previous", {}),
        "esa no": ("youtube_music.esa_no", {}),
        "otra": ("youtube_music.esa_no", {}),
        "que suena": ("youtube_music.get_current_track", {}),
        "que esta sonando": ("youtube_music.get_current_track", {}),
        "baja": ("browser.scroll", {"direction": "down"}),
        "sube": ("browser.scroll", {"direction": "up"}),
        "vuelve": ("browser.back", {}),
    }
    if normalized in fast_path:
        tool, args = fast_path[normalized]
        return RouteResult(kind="mcp", command=normalized, tool=tool, args=args)

    if normalized in {"sube volumen", "baja volumen", "mute"}:
        return RouteResult(kind="codex", command=normalized, reason="system volume tool not implemented")

    if re.match(r"^(?:busca|buscar)\s+(?:que|qué|como|cómo|cuanto|cuánto|por que|por qué)\b", normalized):
        return RouteResult(kind="codex", command=command, reason="open-ended search")

    if re.match(r"^(?:abre|abrir|entra|entrar)\b", normalized):
        return RouteResult(kind="codex", command=command, reason="browser navigation requires reasoning")

    ordinal_music = {
        "la primera": 0,
        "el primero": 0,
        "primera": 0,
        "primero": 0,
        "la segunda": 1,
        "el segundo": 1,
        "segunda": 1,
        "segundo": 1,
        "la tercera": 2,
        "el tercero": 2,
        "tercera": 2,
        "tercero": 2,
    }
    if normalized in ordinal_music:
        return RouteResult(
            kind="mcp",
            command=normalized,
            tool="youtube_music.play_last_search_index",
            args={"index": ordinal_music[normalized]},
        )

    play_match = re.match(
        r"^(?:pon|ponme|reproduce|reproducir|toca|busca|buscar|quiero escuchar)\s+(.+)$",
        normalized,
    )
    if play_match:
        query = _clean_music_query(play_match.group(1))
        return RouteResult(kind="mcp", command=normalized, tool="youtube_music.play", args={"query": query})

    codex_prefixes = (
        "busca ",
        "buscar ",
        "abre ",
        "abrir ",
        "entra ",
        "entrar ",
        "dale ",
        "haz ",
        "dime ",
        "explica ",
        "revisa ",
        "consulta ",
    )
    if normalized.startswith(codex_prefixes):
        return RouteResult(kind="codex", command=command, reason="open-ended command")

    return RouteResult(kind="ignore", command=command, reason="not a command")


def _clean_music_query(query: str) -> str:
    query = re.sub(r"\bde\b", " ", query)
    return " ".join(query.split())
