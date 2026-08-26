from dataclasses import dataclass
from typing import Optional

from .normalize import normalize_text


WAKE_VARIANTS = (
    "apolov2",
    "apolo v2",
    "apolo version 2",
    "apolo",
    "apollo",
    "capolo",
    "a polo",
    "a volo",
    "polo",
    "pola",
    "polvo",
    "por lo",
    "bolo",
    "volo",
    "hola apolov2",
    "hola apolo v2",
    "hola apolo",
    "hola apollo",
    "hola capolo",
    "hola polo",
    "hola pola",
    "hola polvo",
    "hola por lo",
    "hola a polo",
    "hola a volo",
)


@dataclass
class WakeWordResult:
    detected: bool
    command: str = ""
    matched: Optional[str] = None


def strip_wake_word(transcript: str) -> WakeWordResult:
    normalized = _collapse_repeated_wake_words(normalize_text(transcript))
    if not normalized:
        return WakeWordResult(detected=False)

    for variant in WAKE_VARIANTS:
        normalized_variant = normalize_text(variant)
        if normalized == normalized_variant:
            return WakeWordResult(detected=True, command="", matched=variant)
        prefix = f"{normalized_variant} "
        if normalized.startswith(prefix):
            return WakeWordResult(
                detected=True,
                command=normalized[len(prefix) :].strip(),
                matched=variant,
            )

    return WakeWordResult(detected=False)


def likely_wake_attempt(transcript: str) -> bool:
    normalized = normalize_text(transcript)
    if not normalized:
        return False
    wakeish_tokens = {"apolov2", "apolo", "apollo", "capolo", "polo", "pola", "polvo", "volo", "bolo"}
    if any(token in normalized.split() for token in wakeish_tokens):
        return True
    return any(phrase in normalized for phrase in ("a volo", "a polo", "por lo", "hola por"))


def _collapse_repeated_wake_words(normalized: str) -> str:
    tokens = normalized.split()
    result = []
    index = 0
    last_was_wake = False
    while index < len(tokens):
        matched = None
        for variant in sorted((normalize_text(item) for item in WAKE_VARIANTS), key=len, reverse=True):
            parts = variant.split()
            if tokens[index : index + len(parts)] == parts:
                matched = variant
                index += len(parts)
                break
        if matched:
            if not last_was_wake:
                result.extend(matched.split())
                last_was_wake = True
            continue
        result.append(tokens[index])
        last_was_wake = False
        index += 1
    return " ".join(result)
