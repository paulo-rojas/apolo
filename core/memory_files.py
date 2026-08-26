from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from core.config import PROJECT_ROOT, get_int, get_str
from voice.normalize import normalize_text


DEFAULT_VOICE_CORRECTIONS = {
    "cero a": "cierra",
    "cierra discolto": "cierra discord",
    "discourse": "discord",
    "discort": "discord",
    "descord": "discord",
    "discolto": "discord",
    "link in park": "linkin park",
    "link en park": "linkin park",
    "rinking barca": "linkin park",
    "no de rinking barca": "numb de linkin park",
    "nom de linkin park": "numb de linkin park",
    "no de linkin park": "numb de linkin park",
    "siguiente accion": "siguiente cancion",
    "contin a": "continua",
    "reproducen": "reproduce",
    "suele volumen": "sube volumen",
    "prefiro": "prefiero",
    "va a ser volumen": "baja volumen",
    "bajar volumen": "baja volumen",
    "h and ttp": "http",
    "h ttp": "http",
    "httv": "http",
    "httpv": "http",
    "h t tv": "http",
    "hache tete pe": "http",
    "hache te te pe": "http",
    "hache t t p": "http",
    "h t t p": "http",
    "hace 3db": "http",
    "hace tres db": "http",
}


DEFAULT_FAST_INTENTS = {
    "time": ["que hora es", "dime la hora", "hora actual", "dime la hora actual"],
    "date": ["que fecha es", "dime la fecha", "dia actual"],
}


def memory_dir() -> Path:
    configured = get_str("memory.dir", str(PROJECT_ROOT / "memory")) or str(PROJECT_ROOT / "memory")
    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def ensure_memory_files() -> Path:
    base = memory_dir()
    base.mkdir(parents=True, exist_ok=True)
    _ensure_text(
        base / "apolo_profile.md",
        "# Memoria de Apolo\n\n"
        "Este archivo guarda informacion persistente que Apolo puede usar para mantener su personalidad, "
        "preferencias del usuario y detalles utiles.\n\n"
        "## Notas\n",
    )
    _ensure_json(base / "voice_corrections.json", DEFAULT_VOICE_CORRECTIONS)
    _ensure_json(base / "fast_intents.json", DEFAULT_FAST_INTENTS)
    _ensure_json(base / "learned_routes.json", {})
    _ensure_json(base / "repetitive_answers.json", {})
    _ensure_json(base / "system_apps.json", {"aliases": {}})
    _ensure_json(base / "web_shortcuts.json", {"aliases": {}})
    return base


def read_memory_context() -> Dict[str, Any]:
    base = ensure_memory_files()
    return {
        "profile": _read_text(base / "apolo_profile.md")[-4000:],
        "voiceCorrections": _read_json(base / "voice_corrections.json", {}),
        "fastIntents": _read_json(base / "fast_intents.json", {}),
        "learnedRoutes": _read_json(base / "learned_routes.json", {}),
        "repetitiveAnswers": _read_json(base / "repetitive_answers.json", {}),
        "systemApps": _read_json(base / "system_apps.json", {"aliases": {}}),
        "webShortcuts": _read_json(base / "web_shortcuts.json", {"aliases": {}}),
    }


def remember_note(text: str, source: str = "voice") -> Dict[str, Any]:
    text = " ".join(str(text or "").split())
    if not text:
        raise ValueError("memory note is empty")
    base = ensure_memory_files()
    path = base / "apolo_profile.md"
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n- {timestamp} [{source}] {text}\n")
    return {"file": str(path), "text": text}


def add_voice_correction(heard: str, normalized: str) -> Dict[str, Any]:
    source = normalize_text(heard)
    target = normalize_text(normalized)
    if not source or not target:
        raise ValueError("voice correction requires heard and normalized text")
    base = ensure_memory_files()
    path = base / "voice_corrections.json"
    data = _read_json(path, {})
    data[source] = target
    _write_json(path, dict(sorted(data.items())))
    return {"file": str(path), "heard": source, "normalized": target}


def apply_voice_corrections(text: str) -> str:
    corrected = text
    corrections = dict(DEFAULT_VOICE_CORRECTIONS)
    corrections.update(_read_json(ensure_memory_files() / "voice_corrections.json", {}))
    for source, target in sorted(corrections.items(), key=lambda item: len(item[0]), reverse=True):
        corrected = re.sub(rf"\b{re.escape(source)}\b", target, corrected)
    return " ".join(corrected.split())


def match_fast_intent(normalized: str) -> str:
    intents = _read_json(ensure_memory_files() / "fast_intents.json", DEFAULT_FAST_INTENTS)
    for intent, phrases in intents.items():
        if normalized in {normalize_text(phrase) for phrase in phrases}:
            return str(intent)
    return ""


def record_learned_route(command: str, codex_result: Dict[str, Any], elapsed_ms: int) -> Dict[str, Any]:
    normalized = normalize_text(command)
    if not normalized:
        return {}
    base = ensure_memory_files()
    path = base / "learned_routes.json"
    learned = _read_json(path, {})
    entry = learned.get(normalized, {"count": 0})
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["lastElapsedMs"] = elapsed_ms
    entry["lastKind"] = codex_result.get("parsed", {}).get("kind")
    entry["lastText"] = codex_result.get("parsed", {}).get("text")
    entry["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    learned[normalized] = entry
    _write_json(path, learned)
    return entry


def cached_repetitive_answer(command: str) -> Dict[str, Any] | None:
    normalized = normalize_text(command)
    if not normalized:
        return None
    answers = _read_json(ensure_memory_files() / "repetitive_answers.json", {})
    answer = answers.get(normalized)
    return answer if isinstance(answer, dict) else None


def maybe_remember_repetitive_answer(command: str, codex_result: Dict[str, Any], route_entry: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_text(command)
    parsed = codex_result.get("parsed", {})
    answer_text = parsed.get("text") if parsed.get("kind") == "answer" else None
    if not normalized or not answer_text:
        return {"saved": False, "reason": "not an answer"}
    threshold = get_int("memory.repetitive_threshold", 2, minimum=2)
    if int(route_entry.get("count", 0)) < threshold:
        return {"saved": False, "reason": "below threshold", "count": route_entry.get("count", 0)}

    base = ensure_memory_files()
    path = base / "repetitive_answers.json"
    answers = _read_json(path, {})
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    entry = answers.get(normalized, {})
    first_seen = entry.get("firstSeenAt") if isinstance(entry, dict) else None
    answers[normalized] = {
        "answer": " ".join(str(answer_text).split()),
        "count": int(route_entry.get("count", 0)),
        "source": "codex",
        "firstSeenAt": first_seen or now,
        "updatedAt": now,
    }
    _write_json(path, answers)
    return {"saved": True, "file": str(path), "command": normalized, **answers[normalized]}


def _ensure_text(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def _ensure_json(path: Path, default: Dict[str, Any]) -> None:
    if not path.exists():
        _write_json(path, default)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
