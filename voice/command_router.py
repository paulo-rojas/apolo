from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .interpretation import (
    ConversationContext,
    InterpretedCommand,
    InterpretationPipeline,
    InputNormalizer,
)


@dataclass
class RouteResult:
    kind: str
    command: str
    tool: str = ""
    args: Optional[Dict[str, Any]] = None
    reason: str = ""
    interpretation: Optional[InterpretedCommand] = None

    def as_dict(self) -> Dict[str, Any]:
        data = {
            "kind": self.kind,
            "command": self.command,
            "tool": self.tool,
            "args": self.args or {},
            "reason": self.reason,
        }
        if self.interpretation:
            data["interpretation"] = self.interpretation.as_dict()
        return data


def route_command(command: str, state: Optional[Any] = None) -> RouteResult:
    context = ConversationContext(state).get()
    interpreted = InterpretationPipeline().interpret(command, context)
    route = _route_interpreted(interpreted)
    if route.kind == "mcp":
        ConversationContext(state).update_from_interpretation(interpreted)
    return route


def normalize_command(command: str) -> str:
    return InputNormalizer().normalize(command)


def _route_interpreted(interpreted: InterpretedCommand) -> RouteResult:
    normalized = interpreted.normalized_text
    intent = interpreted.intent

    if not normalized:
        return _route("ignore", interpreted, reason="empty command")

    if interpreted.reason == "missing command target":
        return _route("session", interpreted, reason="missing command target")

    if intent == "pause_music":
        return _route("mcp", interpreted, tool="youtube_music.pause")
    if intent == "resume_music":
        return _route("mcp", interpreted, tool="youtube_music.resume")
    if intent == "next_track":
        variant = interpreted.entities.get("variant")
        tool = "youtube_music.esa_no" if variant in {"esa no", "otra"} else "youtube_music.next"
        return _route("mcp", interpreted, tool=tool)
    if intent == "previous_track":
        return _route("mcp", interpreted, tool="youtube_music.previous")
    if intent == "current_track":
        return _route("mcp", interpreted, tool="youtube_music.get_current_track")
    if intent == "browser_scroll":
        return _route("mcp", interpreted, tool="browser.scroll", args=interpreted.entities)
    if intent == "browser_back":
        return _route("mcp", interpreted, tool="browser.back")
    if intent == "browser_click":
        return _route("mcp", interpreted, tool="browser.smart_click", args=interpreted.entities)

    if intent == "set_volume":
        return _route("mcp", interpreted, tool="system.set_volume", args=interpreted.entities)

    if intent == "codex_status":
        return _route("status", interpreted, command="codex", reason="codex status")

    if intent == "remember_information":
        return _route(
            "memory",
            interpreted,
            command="remember",
            args={"text": interpreted.entities.get("text", "")},
            reason="memory note",
        )

    if intent in {"rest", "shutdown"}:
        return _route("local", interpreted, command=intent, reason="local fast intent")
    if intent == "get_time":
        return _route("local", interpreted, command="time", reason="local fast intent")
    if intent == "get_date":
        return _route("local", interpreted, command="date", reason="local fast intent")
    if intent == "assistant_status":
        return _route("local", interpreted, command="assistant_status", reason="local fast intent")
    if intent in {"time", "date"}:
        return _route("local", interpreted, command=intent, reason="local fast intent")

    if intent == "open_application":
        return _route(
            "mcp",
            interpreted,
            tool="system.open_app",
            args={"name": interpreted.entities.get("name", "")},
            reason="system app launch",
        )
    if intent == "close_application":
        return _route(
            "mcp",
            interpreted,
            tool="system.close_app",
            args={"name": interpreted.entities.get("name", "")},
            reason="system app close",
        )
    if intent == "web_search":
        return _route(
            "mcp",
            interpreted,
            tool="web.search_google",
            args={"query": interpreted.entities.get("query", "")},
            reason="web search",
        )
    if intent == "web_open":
        return _route(
            "mcp",
            interpreted,
            tool="web.open",
            args={"target": interpreted.entities.get("target", "")},
            reason="web open",
        )
    if intent == "play_music_index":
        return _route(
            "mcp",
            interpreted,
            tool="youtube_music.play_last_search_index",
            args={"index": interpreted.entities.get("index", 0)},
        )
    if intent == "play_music" and not interpreted.needs_reasoning:
        return _route(
            "mcp",
            interpreted,
            tool="youtube_music.play",
            args=_music_tool_args(interpreted.entities),
        )

    if interpreted.needs_reasoning:
        reason = interpreted.reason or "local parser did not understand command"
        command = interpreted.entities.get("text") or _codex_command(interpreted) or interpreted.raw_text
        return _route("codex", interpreted, command=command, reason=reason)

    return _route("ignore", interpreted, reason=interpreted.reason or "not a command")


def _route(
    kind: str,
    interpreted: InterpretedCommand,
    command: Optional[str] = None,
    tool: str = "",
    args: Optional[Dict[str, Any]] = None,
    reason: str = "",
) -> RouteResult:
    return RouteResult(
        kind=kind,
        command=command if command is not None else interpreted.normalized_text,
        tool=tool,
        args=args or {},
        reason=reason or interpreted.reason,
        interpretation=interpreted,
    )


def _music_tool_args(entities: Dict[str, Any]) -> Dict[str, Any]:
    args = {"query": str(entities.get("query") or "").strip()}
    for key in ("artist", "album"):
        value = str(entities.get(key) or "").strip()
        if value:
            args[key] = value
    platform = str(entities.get("platform") or "").strip()
    if platform:
        args["platform"] = platform
    return args


def _codex_command(interpreted: InterpretedCommand) -> str:
    if interpreted.reason == "browser navigation requires reasoning":
        return interpreted.raw_text
    if interpreted.reason == "open-ended search":
        return interpreted.normalized_text
    if interpreted.reason == "open-ended question":
        if interpreted.normalized_text.startswith("que suena protocolo "):
            return interpreted.normalized_text.replace("que suena ", "", 1)
        return interpreted.normalized_text
    return interpreted.normalized_text
