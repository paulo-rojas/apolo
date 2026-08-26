from __future__ import annotations

import re
from typing import Any, Dict

from voice.normalize import normalize_text


class ToolContractError(ValueError):
    pass


RAW_LANGUAGE_KEYS = {
    "command",
    "normalized_text",
    "raw_text",
    "transcript",
    "utterance",
}

RAW_LANGUAGE_PATTERNS = (
    r"\b(?:apolo|apolov2|apollo|hola apolo|hola polo)\b",
    r"\b(?:eh|ehh|ehm|este|bueno|a ver|o sea)\b",
    r"\b(?:ponme|pon|reproduce|quiero escuchar|abre|busca|cierra|sierra)\b.+\b(?:de|en)\b",
)


def validate_structured_tool_args(tool: str, args: Dict[str, Any]) -> None:
    if not isinstance(args, dict):
        raise ToolContractError(f"{tool} args must be an object")
    forbidden = RAW_LANGUAGE_KEYS & set(args)
    if forbidden:
        raise ToolContractError(f"{tool} received raw language keys: {', '.join(sorted(forbidden))}")
    for key, value in args.items():
        if not isinstance(value, str):
            continue
        if _looks_like_raw_voice_command(value):
            raise ToolContractError(f"{tool}.{key} looks like raw voice input")


def _looks_like_raw_voice_command(value: str) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in RAW_LANGUAGE_PATTERNS)
