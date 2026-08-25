from dataclasses import dataclass
from typing import Optional

from .normalize import normalize_text


WAKE_VARIANTS = ("apolo", "apollo", "a polo", "hola apolo", "hola polo")


@dataclass
class WakeWordResult:
    detected: bool
    command: str = ""
    matched: Optional[str] = None


def strip_wake_word(transcript: str) -> WakeWordResult:
    normalized = normalize_text(transcript)
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
