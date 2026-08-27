from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, Optional

from core.config import get_float, get_int
from core.memory_files import apply_voice_corrections, match_fast_intent
from core.system_apps import known_app_alias
from core.web_shortcuts import known_web_alias

from .normalize import normalize_text


@dataclass(frozen=True)
class IntentSpec:
    name: str
    required_entities: tuple[str, ...] = ()
    optional_entities: tuple[str, ...] = ()
    tool_handler: str = ""
    validation_rules: tuple[str, ...] = ()
    voice_aliases: tuple[tuple[str, float], ...] = ()


@dataclass
class SemanticNode:
    role: str
    text: str = ""
    children: list["SemanticNode"] = field(default_factory=list)

    def child(self, role: str) -> Optional["SemanticNode"]:
        return next((child for child in self.children if child.role == role), None)

    def as_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"role": self.role}
        if self.text:
            data["text"] = self.text
        if self.children:
            data["children"] = [child.as_dict() for child in self.children]
        return data


def _semantic_tree_from_command(intent: str, normalized_text: str, entities: Dict[str, Any]) -> SemanticNode:
    root = SemanticNode(intent, text=normalized_text)
    for role, value in entities.items():
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            children = [SemanticNode(str(child_role), text=str(child_value)) for child_role, child_value in value.items()]
            root.children.append(SemanticNode(str(role), children=children))
        elif isinstance(value, (list, tuple)):
            root.children.append(
                SemanticNode(str(role), children=[SemanticNode("value", text=str(item)) for item in value])
            )
        else:
            root.children.append(SemanticNode(str(role), text=str(value)))
    return root


@dataclass
class MemoryDecision:
    memory_action: str = "none"
    memory_type: str = ""
    value: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if data["memory_action"] == "none":
            return {"memory_action": "none"}
        return data


@dataclass
class InterpretedCommand:
    raw_text: str
    normalized_text: str
    intent: str
    entities: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    needs_reasoning: bool = False
    needs_memory: bool = False
    source: str = "rule"
    memory: MemoryDecision = field(default_factory=MemoryDecision)
    semantic_tree: Optional[SemanticNode] = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.semantic_tree is None and self.intent != "unknown":
            self.semantic_tree = _semantic_tree_from_command(self.intent, self.normalized_text, self.entities)

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["memory"] = self.memory.as_dict()
        data["semantic_tree"] = self.semantic_tree.as_dict() if self.semantic_tree else None
        return data


class IntentRegistry:
    def __init__(self, specs: Optional[Iterable[IntentSpec]] = None):
        self._specs = {spec.name: spec for spec in (specs or DEFAULT_INTENTS)}

    def get(self, name: str) -> Optional[IntentSpec]:
        return self._specs.get(name)

    def tool_for(self, name: str) -> str:
        spec = self.get(name)
        return spec.tool_handler if spec else ""

    def simple_aliases(self) -> Dict[str, tuple[str, float]]:
        aliases: Dict[str, tuple[str, float]] = {}
        for spec in self._specs.values():
            for alias, confidence in spec.voice_aliases:
                aliases[alias] = (spec.name, confidence)
        return aliases


class ConversationContext:
    def __init__(self, state: Optional[Any] = None):
        self.state = state

    def get(self) -> Dict[str, Any]:
        data = self.state.get("conversationContext", {}) if self.state else {}
        if not isinstance(data, dict):
            return {}
        ttl = get_int("nlu.context_ttl_seconds", 180, minimum=1)
        updated_at = float(data.get("updatedAt") or 0)
        if updated_at and time.time() - updated_at <= ttl:
            return data
        return {}

    def update_from_interpretation(self, interpreted: InterpretedCommand) -> Dict[str, Any]:
        if not self.state or interpreted.intent == "unknown":
            return self.get()
        entities = interpreted.entities or {}
        if not entities and interpreted.intent not in {"pause_music", "resume_music", "next_track", "previous_track"}:
            return self.get()
        data = {
            "updatedAt": time.time(),
            "lastIntent": interpreted.intent,
            "lastCommand": {
                "intent": interpreted.intent,
                "entities": dict(entities),
                "semanticTree": interpreted.semantic_tree.as_dict() if interpreted.semantic_tree else None,
            },
        }
        if interpreted.intent == "play_music":
            data["music"] = {
                "query": entities.get("query"),
                "artist": entities.get("artist"),
                "album": entities.get("album"),
            }
        self.state.set("conversationContext", data)
        return data


class LocalModelIntentResolver:
    """Interface placeholder for a cheap local NLU model.

    The default implementation is intentionally inert. A future adapter can
    subclass this and return an InterpretedCommand without changing the router.
    """

    def interpret(self, raw_text: str, normalized_text: str, context: Dict[str, Any]) -> Optional[InterpretedCommand]:
        return None


class ReasoningProvider:
    """Interface placeholder for Codex or another advanced reasoner."""

    def interpret(self, raw_text: str, normalized_text: str, context: Dict[str, Any]) -> InterpretedCommand:
        return InterpretedCommand(
            raw_text=raw_text,
            normalized_text=normalized_text,
            intent="unknown",
            confidence=0.35,
            needs_reasoning=True,
            source="codex",
            reason="advanced reasoning required",
        )


class InputNormalizer:
    def normalize(self, text: str) -> str:
        normalized = apply_voice_corrections(normalize_text(text))
        normalized = self._drop_leading_wake_word(normalized)
        normalized = self._apply_correction_markers(normalized)
        normalized = self._drop_fillers(normalized)
        normalized = self._collapse_repetitions(normalized)
        return " ".join(normalized.split())

    def _drop_leading_wake_word(self, normalized: str) -> str:
        wake_variants = (
            "hola apolov2",
            "hola apolo v2",
            "hola apolo",
            "hola apollo",
            "hola capolo",
            "hola polo",
            "hola pola",
            "hola polvo",
            "apolov2",
            "apolo v2",
            "apolo",
            "apollo",
            "capolo",
            "a polo",
            "a volo",
            "polo",
            "pola",
            "polvo",
        )
        for variant in sorted(wake_variants, key=len, reverse=True):
            if normalized == variant:
                return ""
            if normalized.startswith(f"{variant} "):
                return normalized[len(variant) :].strip()
        return normalized

    def _apply_correction_markers(self, normalized: str) -> str:
        patterns = (
            r"\b(?:no|no no|mejor|mas bien)\s*,?\s*(.+)$",
            r"\b(?:perdon|corrijo)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                candidate = match.group(1).strip()
                if _starts_like_command(candidate):
                    return candidate
        return normalized

    def _drop_fillers(self, normalized: str) -> str:
        fillers = {
            "eh",
            "ehh",
            "ehm",
            "emm",
            "este",
            "bueno",
        }
        tokens = [token for token in normalized.split() if token not in fillers]
        text = " ".join(tokens)
        text = re.sub(r"\ba ver\b", " ", text)
        text = re.sub(r"\bo sea\b", " ", text)
        return " ".join(text.split())

    def _collapse_repetitions(self, normalized: str) -> str:
        tokens = normalized.split()
        if not tokens:
            return ""
        collapsed: list[str] = []
        for token in tokens:
            if collapsed and collapsed[-1] == token and token in REPEATABLE_NOISE:
                continue
            collapsed.append(token)
        text = " ".join(collapsed)
        for phrase in ("quiero escuchar", "busca", "buscar", "pon", "ponme", "abre", "abrir"):
            text = re.sub(rf"\b{re.escape(phrase)}\s+{re.escape(phrase)}\b", phrase, text)
        text = re.sub(r"\bpon\s+ponme\b", "ponme", text)
        return text


class DeterministicIntentResolver:
    def __init__(self, registry: Optional[IntentRegistry] = None):
        self.registry = registry or IntentRegistry()

    def interpret(self, raw_text: str, normalized_text: str, context: Optional[Dict[str, Any]] = None) -> InterpretedCommand:
        context = context or {}
        if not normalized_text:
            return _unknown(raw_text, normalized_text, 0.0, "empty command")

        if normalized_text in INCOMPLETE_COMMANDS:
            return InterpretedCommand(raw_text, normalized_text, "unknown", confidence=0.45, reason="missing command target")

        compound = self._compound(raw_text, normalized_text)
        if compound:
            return compound

        simple = self._simple_control(raw_text, normalized_text)
        if simple:
            return simple

        memory = self._memory(raw_text, normalized_text)
        if memory:
            return memory

        local = self._local(raw_text, normalized_text)
        if local:
            return local

        app = self._application(raw_text, normalized_text)
        if app:
            return app

        web = self._web(raw_text, normalized_text)
        if web:
            return web

        music = self._music(raw_text, normalized_text, context)
        if music:
            return music

        if _open_question(normalized_text):
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "unknown",
                confidence=0.62,
                needs_reasoning=True,
                source="rule",
                reason="open-ended question",
            )

        if normalized_text.startswith(CODEX_PREFIXES):
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "unknown",
                confidence=0.55,
                needs_reasoning=True,
                source="rule",
                reason="open-ended command",
            )

        return _unknown(raw_text, normalized_text, 0.25, "not a command")

    def _compound(self, raw_text: str, normalized_text: str) -> Optional[InterpretedCommand]:
        match = re.match(
            r"^(?:abre|abrir|entra|entrar)\s+(youtube(?:\s+music)?|ytmusic)\s+y\s+"
            r"(?:pon|ponme|reproduce|reproducir|toca|quiero escuchar)\s+(.+)$",
            normalized_text,
        )
        if not match:
            return None
        target = "youtube_music"
        music_text = match.group(2).strip()
        tree, music = _parse_music_frame(music_text)
        root = SemanticNode("open_and_play_music", text=normalized_text)
        root.children.append(SemanticNode("target", target))
        root.children.append(tree)
        return InterpretedCommand(
            raw_text,
            normalized_text,
            "open_and_play_music",
            {"target": target, "music": music},
            0.93,
            source="rule",
            semantic_tree=root,
        )

    def _simple_control(self, raw_text: str, normalized_text: str) -> Optional[InterpretedCommand]:
        controls = self.registry.simple_aliases()
        if normalized_text in controls:
            intent, confidence = controls[normalized_text]
            entities = {"variant": normalized_text} if normalized_text in {"esa no", "otra"} else {}
            return InterpretedCommand(raw_text, normalized_text, intent, entities, confidence, source="alias")
        fuzzy = _short_command_alias_match(normalized_text, controls)
        if fuzzy:
            alias, intent, confidence = fuzzy
            entities = {"variant": alias} if alias in {"esa no", "otra"} else {}
            tree = _semantic_tree_from_command(intent, alias, entities)
            return InterpretedCommand(
                raw_text,
                alias,
                intent,
                entities,
                confidence,
                source="asr_fuzzy",
                semantic_tree=tree,
                reason=f"matched short command alias from {normalized_text}",
            )
        if normalized_text in {"sube", "baja"}:
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "browser_scroll",
                {"direction": "up" if normalized_text == "sube" else "down"},
                0.92,
            )
        if normalized_text == "vuelve":
            return InterpretedCommand(raw_text, normalized_text, "browser_back", confidence=0.92)
        click = re.match(
            r"^(?:dale|da|haz|has)\s+clic\s+(?:al\s+|a\s+|en\s+el\s+|en\s+la\s+)?(?:boton\s+de\s+|boton\s+|button\s+)?(.+)$",
            normalized_text,
        )
        if click:
            target = click.group(1).strip()
            if target:
                return InterpretedCommand(raw_text, normalized_text, "browser_click", {"target": target}, 0.9)
        button = re.match(r"^(?:boton|button)\s+(?:de\s+)?(.+)$", normalized_text)
        if button:
            target = button.group(1).strip()
            if target:
                return InterpretedCommand(raw_text, normalized_text, "browser_click", {"target": target}, 0.88)
        if normalized_text in COMMON_BROWSER_BUTTONS:
            return InterpretedCommand(raw_text, normalized_text, "browser_click", {"target": normalized_text}, 0.86)
        volume_text = normalized_text
        volume = re.match(
            r"^(?:sube|baja|pon|fija|cambia)(?:\s+el)?\s+volumen(?:\s+a\s+([a-z0-9 ]+))?$",
            volume_text,
        )
        if not volume:
            volume_text = _best_phrase_match(
                normalized_text,
                ("sube volumen", "sube el volumen", "baja volumen", "baja el volumen"),
                threshold=0.84,
            ) or normalized_text
            volume = re.match(
                r"^(?:sube|baja|pon|fija|cambia)(?:\s+el)?\s+volumen(?:\s+a\s+([a-z0-9 ]+))?$",
                volume_text,
            )
        if volume:
            entities: Dict[str, Any] = {}
            if volume.group(1):
                level = _parse_volume_level(volume.group(1))
                if level is not None:
                    entities["level"] = min(100, max(0, level))
            direction = volume_text.split()[0]
            if direction in {"sube", "baja"} and not entities:
                entities["direction"] = "up" if direction == "sube" else "down"
            return InterpretedCommand(raw_text, normalized_text, "set_volume", entities, 0.88)
        return None

    def _memory(self, raw_text: str, normalized_text: str) -> Optional[InterpretedCommand]:
        match = re.match(r"^(?:recuerda que|recuerda|aprende que|aprende|guarda que|guarda)\s+(.+)$", normalized_text)
        if not match:
            return None
        text = match.group(1).strip()
        return InterpretedCommand(
            raw_text,
            normalized_text,
            "remember_information",
            {"text": text},
            0.95,
            needs_memory=True,
            source="rule",
            memory=MemoryDecision("store", "fact", {"text": text}),
            reason="memory note",
        )

    def _application(self, raw_text: str, normalized_text: str) -> Optional[InterpretedCommand]:
        close_match = re.match(
            r"^(?:cierra|cierre|cerrar|sierra|termina|termine|terminar)\s+(?:la\s+|el\s+)?(?:(?:aplicacion|app|programa)\s+)?(.+)$",
            normalized_text,
        )
        if close_match:
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "close_application",
                {"name": close_match.group(1).strip()},
                0.91,
            )
        open_match = re.match(
            r"^(?:inicia|inicie|iniciar|lanza|lance|lanzar|ejecuta|ejecute|ejecutar)\s+(.+)$",
            normalized_text,
        )
        if not open_match:
            open_match = re.match(
                r"^(?:abre|abra|abrir)\s+(?:la\s+|el\s+)?(?:aplicacion|app|programa)\s+(.+)$",
                normalized_text,
            )
        if open_match:
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "open_application",
                {"name": open_match.group(1).strip()},
                0.91,
            )
        browser_match = re.match(r"^(?:abre|abra|abrir)\s+(?:el\s+|la\s+)?(?:navegador|browser|brave)$", normalized_text)
        if browser_match:
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "open_application",
                {"name": "navegador"},
                0.91,
            )
        open_simple = re.match(r"^(?:abre|abra|abrir)\s+(.+)$", normalized_text)
        if open_simple and known_app_alias(open_simple.group(1)):
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "open_application",
                {"name": open_simple.group(1).strip()},
                0.9,
                source="alias",
            )
        return None

    def _web(self, raw_text: str, normalized_text: str) -> Optional[InterpretedCommand]:
        question = _open_question(normalized_text)
        if question and normalized_text.startswith(("busca ", "buscar ")):
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "unknown",
                {"query": question},
                0.62,
                needs_reasoning=True,
                reason="open-ended search",
            )
        match = re.match(r"^(?:busca|buscar)\s+(.+?)\s+en\s+google$", normalized_text)
        if match:
            return InterpretedCommand(raw_text, normalized_text, "web_search", {"query": match.group(1).strip()}, 0.94)
        match = re.match(r"^(?:googlea|googlear|busca|buscar)\s+(.+)$", normalized_text)
        if match and _is_ambiguous_search(match.group(1)):
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "unknown",
                {"query": match.group(1).strip()},
                0.52,
                needs_reasoning=True,
                reason="ambiguous search reference",
            )
        if match and not _looks_like_music_search(match.group(1)):
            return InterpretedCommand(raw_text, normalized_text, "web_search", {"query": match.group(1).strip()}, 0.86)
        open_match = re.match(r"^(?:abre|abrir|entra|entrar)\s+(?:la\s+pagina\s+|el\s+sitio\s+|la\s+web\s+)?(.+)$", normalized_text)
        if not open_match:
            return None
        target = _drop_leading_article(open_match.group(1).strip())
        if known_app_alias(target):
            return None
        if known_web_alias(target) or "." in target or len(target.split()) == 1:
            return InterpretedCommand(raw_text, normalized_text, "web_open", {"target": target}, 0.88)
        return InterpretedCommand(
            raw_text,
            normalized_text,
            "unknown",
            {"target": target},
            0.58,
            needs_reasoning=True,
            reason="browser navigation requires reasoning",
        )

    def _local(self, raw_text: str, normalized_text: str) -> Optional[InterpretedCommand]:
        learned = match_fast_intent(normalized_text)
        if learned:
            return InterpretedCommand(raw_text, normalized_text, learned, confidence=0.9, source="memory")
        if normalized_text in {"descansa", "descansar", "duerme", "duermete", "vete a descansar"}:
            return InterpretedCommand(raw_text, normalized_text, "rest", confidence=0.96)
        if normalized_text in {
            "termina la sesion",
            "terminar la sesion",
            "termina sesion",
            "terminar sesion",
            "cierra la sesion",
            "cierra sesion",
            "apagate",
            "apaga apolov2",
            "apaga apolo",
        }:
            return InterpretedCommand(raw_text, normalized_text, "shutdown", confidence=0.96)
        tokens = set(normalized_text.split())
        if "hora" in tokens and tokens & {"dime", "di", "decime", "actual", "es", "tienes", "tiene"}:
            return InterpretedCommand(raw_text, normalized_text, "get_time", confidence=0.93)
        if normalized_text in {"que hora es", "la hora", "hora actual"}:
            return InterpretedCommand(raw_text, normalized_text, "get_time", confidence=0.93)
        if "fecha" in tokens or ("dia" in tokens and tokens & {"hoy", "actual"}):
            return InterpretedCommand(raw_text, normalized_text, "get_date", confidence=0.91)
        if "dias" in tokens and "hoy" in tokens:
            return InterpretedCommand(raw_text, normalized_text, "get_date", confidence=0.86, source="alias")
        if _looks_like_codex_status_question(normalized_text):
            return InterpretedCommand(raw_text, normalized_text, "codex_status", confidence=0.9)
        if normalized_text in CONVERSATION_CHECKS:
            return InterpretedCommand(raw_text, normalized_text, "assistant_status", {"text": normalized_text}, 0.9)
        return None

    def _music(self, raw_text: str, normalized_text: str, context: Dict[str, Any]) -> Optional[InterpretedCommand]:
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
        if normalized_text in ordinal_music:
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "play_music_index",
                {"index": ordinal_music[normalized_text]},
                0.92,
            )
        same_group = re.match(r"^(?:pon|ponme|reproduce|reproducir|toca)\s+otra\s+del\s+mismo\s+(?:grupo|artista)$", normalized_text)
        if same_group:
            artist = (context.get("music") or {}).get("artist")
            if artist:
                return InterpretedCommand(
                    raw_text,
                    normalized_text,
                    "play_music",
                    {"query": f"otra de {artist}", "artist": artist, "context_ref": "same_artist"},
                    0.82,
                    source="context",
                )
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "play_music",
                {"query": "otra"},
                0.52,
                needs_reasoning=True,
                reason="missing artist context",
            )
        artist_only = re.match(r"^de\s+(.+)$", normalized_text)
        if artist_only:
            tree, entities = _parse_music_frame(normalized_text)
            if _looks_like_garbled_artist_reference(entities.get("artist", "")):
                return _unknown(raw_text, normalized_text, 0.3, "not a command")
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "play_music",
                entities,
                0.88,
                source="alias",
                semantic_tree=tree,
            )
        play_match = re.match(
            r"^(?:pon|ponme|ponle(?:\s+mi\s+cancion)?|reproduce|reproducir|toca|quiero escuchar)\s+(.+)$",
            normalized_text,
        )
        if not play_match:
            play_match = re.match(r"^(?:busca|buscar)\s+(.+)$", normalized_text)
            if play_match and not _looks_like_music_search(play_match.group(1)):
                return None
        if not play_match:
            return None
        tree, entities = _parse_music_frame(play_match.group(1))
        if _is_ambiguous_reference(entities.get("query", "")):
            return InterpretedCommand(
                raw_text,
                normalized_text,
                "play_music",
                entities,
                0.5,
                needs_reasoning=True,
                semantic_tree=tree,
                reason="ambiguous music reference",
            )
        return InterpretedCommand(
            raw_text,
            normalized_text,
            "play_music",
            entities,
            0.94,
            source="alias",
            semantic_tree=tree,
        )


class InterpretationPipeline:
    def __init__(
        self,
        normalizer: Optional[InputNormalizer] = None,
        deterministic: Optional[DeterministicIntentResolver] = None,
        local_model: Optional[LocalModelIntentResolver] = None,
        reasoning: Optional[ReasoningProvider] = None,
    ):
        self.normalizer = normalizer or InputNormalizer()
        self.deterministic = deterministic or DeterministicIntentResolver()
        self.local_model = local_model or LocalModelIntentResolver()
        self.reasoning = reasoning or ReasoningProvider()

    def interpret(self, raw_text: str, context: Optional[Dict[str, Any]] = None) -> InterpretedCommand:
        context = context or {}
        normalized = self.normalizer.normalize(raw_text)
        deterministic = self.deterministic.interpret(raw_text, normalized, context)
        if deterministic.confidence >= execute_threshold() or deterministic.needs_reasoning:
            return deterministic
        if deterministic.confidence >= retry_threshold():
            try:
                local = self.local_model.interpret(raw_text, normalized, context)
                if local:
                    return local
            except Exception as error:
                deterministic.reason = f"local model failed: {error}"
        if deterministic.confidence < retry_threshold() and deterministic.reason != "not a command":
            deterministic.needs_reasoning = True
        return deterministic


def execute_threshold() -> float:
    return get_float("nlu.execute_confidence", 0.85, minimum=0.0)


def retry_threshold() -> float:
    return get_float("nlu.retry_confidence", 0.60, minimum=0.0)


def _extract_music_entities(text: str) -> Dict[str, Any]:
    return _parse_music_frame(text)[1]


def _parse_music_frame(text: str) -> tuple[SemanticNode, Dict[str, Any]]:
    tree = _parse_music_tree(text)
    return tree, _entities_from_music_tree(tree)


def _parse_music_tree(text: str) -> SemanticNode:
    cleaned, platform = _split_music_platform(" ".join(text.split()))
    root = SemanticNode("play_music", text=cleaned)
    media = SemanticNode("media_query")
    root.children.append(media)
    if platform:
        root.children.append(SemanticNode("platform", platform))
    artist_only = re.match(r"^de\s+(.+)$", cleaned)
    if artist_only:
        artist = _clean_music_artist(artist_only.group(1))
        media.children.append(SemanticNode("artist", artist))
        return root
    reverse_match = re.match(r"^la\s+de\s+(.+)\s+(.+)$", cleaned)
    if reverse_match:
        tokens = cleaned.removeprefix("la de ").split()
        if len(tokens) >= 2:
            media.children.append(SemanticNode("query", _clean_music_query(tokens[-1])))
            media.children.append(SemanticNode("artist", _clean_music_artist(" ".join(tokens[:-1]))))
            return root
    match = re.match(r"^(.+?)\s+de\s+(.+)$", cleaned)
    if match:
        media.children.append(SemanticNode("query", _clean_music_query(match.group(1))))
        media.children.append(SemanticNode("artist", _clean_music_artist(match.group(2))))
        return root
    media.children.append(SemanticNode("query", _clean_music_query(cleaned)))
    return root


def _entities_from_music_tree(tree: SemanticNode) -> Dict[str, Any]:
    entities: Dict[str, Any] = {}
    media = tree.child("media_query")
    if media:
        for child in media.children:
            if child.role in {"query", "artist", "album"}:
                entities[child.role] = child.text
        if "artist" in entities and "query" not in entities:
            entities["query"] = ""
    platform = tree.child("platform")
    if platform:
        entities["platform"] = platform.text
    if not entities.get("query") and "artist" not in entities:
        entities["query"] = ""
    return entities


def _clean_music_query(query: str) -> str:
    query = re.sub(r"\b(?:la\s+)?original\b", " ", query)
    return " ".join(query.split())


def _clean_music_artist(artist: str) -> str:
    artist = _clean_music_query(artist)
    artist = re.sub(r"\s+en\s+(?:youtube|youtube music|ytmusic)$", "", artist)
    return " ".join(artist.split())


def _parse_volume_level(text: str) -> Optional[int]:
    value = " ".join(str(text or "").split())
    if not value:
        return None
    if value.isdigit():
        return int(value)
    number_words = {
        "cero": 0,
        "diez": 10,
        "veinte": 20,
        "treinta": 30,
        "cuarenta": 40,
        "cincuenta": 50,
        "sesenta": 60,
        "setenta": 70,
        "ochenta": 80,
        "noventa": 90,
        "cien": 100,
    }
    return number_words.get(value)


def _short_command_alias_match(normalized_text: str, controls: Dict[str, tuple[str, float]]) -> Optional[tuple[str, str, float]]:
    if len(normalized_text) > 28 or len(normalized_text.split()) > 4:
        return None
    candidates: list[tuple[str, str, float, float]] = []
    for alias, (intent, base_confidence) in controls.items():
        if abs(len(alias) - len(normalized_text)) > 6:
            continue
        score = SequenceMatcher(None, normalized_text, alias).ratio()
        if score < 0.86:
            continue
        if not _shares_command_shape(normalized_text, alias):
            continue
        candidates.append((alias, intent, min(base_confidence, 0.9), score))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[3], reverse=True)
    if len(candidates) > 1 and candidates[0][3] - candidates[1][3] < 0.08:
        return None
    return candidates[0][:3]


def _shares_command_shape(text: str, alias: str) -> bool:
    text_tokens = text.split()
    alias_tokens = alias.split()
    if not text_tokens or not alias_tokens:
        return False
    if text_tokens[0] in {"no", "nunca", "sin"}:
        return False
    if text_tokens[0][0] == alias_tokens[0][0]:
        return True
    return bool(set(text_tokens) & set(alias_tokens))


def _best_phrase_match(text: str, candidates: Iterable[str], threshold: float) -> Optional[str]:
    if len(text) > 30 or len(text.split()) > 5:
        return None
    best_text = ""
    best_score = 0.0
    for candidate in candidates:
        score = SequenceMatcher(None, text, candidate).ratio()
        if score > best_score:
            best_text = candidate
            best_score = score
    return best_text if best_score >= threshold else None


def _drop_leading_article(text: str) -> str:
    return re.sub(r"^(?:el|la|los|las)\s+", "", str(text or "").strip())


def _split_music_platform(text: str) -> tuple[str, str]:
    platform_aliases = {
        "youtube": "youtube",
        "youtube music": "youtube_music",
        "ytmusic": "youtube_music",
        "spotify": "spotify",
        "apple music": "apple_music",
    }
    for alias, platform in sorted(platform_aliases.items(), key=lambda item: len(item[0]), reverse=True):
        match = re.search(rf"\s+en\s+{re.escape(alias)}$", text)
        if match:
            return text[: match.start()].strip(), platform
    return text, ""


def _unknown(raw_text: str, normalized_text: str, confidence: float, reason: str) -> InterpretedCommand:
    return InterpretedCommand(
        raw_text=raw_text,
        normalized_text=normalized_text,
        intent="unknown",
        confidence=confidence,
        needs_reasoning=confidence >= retry_threshold(),
        source="rule",
        reason=reason,
    )


def _starts_like_command(text: str) -> bool:
    return text.startswith(
        (
            "pon ",
            "ponme ",
            "reproduce ",
            "busca ",
            "buscar ",
            "abre ",
            "abrir ",
            "cierra ",
            "sierra ",
            "sube ",
            "baja ",
        )
    )


def _looks_like_music_search(text: str) -> bool:
    tokens = set(text.split())
    return bool(tokens & {"cancion", "musica", "playlist", "album", "youtube", "ytmusic"})


def _is_ambiguous_reference(query: str) -> bool:
    return query.strip() in {"eso", "esa", "ese", "lo de ayer", "eso que te dije"}


def _is_ambiguous_search(query: str) -> bool:
    return query.strip() in {"eso", "eso que te dije", "lo de ayer"}


def _looks_like_garbled_artist_reference(artist: str) -> bool:
    words = str(artist or "").split()
    tokens = set(words)
    if tokens & {"alble", "ble", "pumbly", "meldia"}:
        return True
    if len(words) == 1 and words[0] not in _KNOWN_SINGLE_WORD_ARTISTS:
        return True
    return False


_KNOWN_SINGLE_WORD_ARTISTS = {
    "adele",
    "beatles",
    "coldplay",
    "metallica",
    "nirvana",
    "oasis",
    "queen",
    "radiohead",
    "shakira",
}


def _open_question(normalized: str) -> str:
    if re.match(r"^(?:busca|buscar)\s+(?:que|como|cuanto|por que)\b", normalized):
        return normalized
    if re.match(r"^(?:que es|que significa|como funciona|para que sirve)\b", normalized):
        return normalized
    if re.match(r"^(?:define|defineme|explica|explicame)\b", normalized):
        return normalized
    if "protocolo" in normalized.split():
        cleaned = re.sub(r"^(?:que suena|que esta sonando)\s+", "", normalized).strip()
        return cleaned or normalized
    return ""


def _looks_like_codex_status_question(normalized: str) -> bool:
    if "codex" not in normalized:
        return False
    status_terms = {
        "conexion",
        "conecxion",
        "esconexion",
        "desconexion",
        "conectado",
        "conectada",
        "disponible",
        "funciona",
        "responde",
        "activo",
        "activa",
        "estado",
        "tiene",
        "tienes",
        "hay",
    }
    return any(term in normalized.split() for term in status_terms)


DEFAULT_INTENTS = (
    IntentSpec("play_music", (), ("query", "artist", "album", "platform"), "youtube_music.play"),
    IntentSpec(
        "open_and_play_music",
        ("target", "music"),
        tool_handler="",
    ),
    IntentSpec(
        "pause_music",
        tool_handler="youtube_music.pause",
        voice_aliases=(("pausa", 0.98), ("pausar", 0.97), ("pause", 0.96)),
    ),
    IntentSpec(
        "resume_music",
        tool_handler="youtube_music.resume",
        voice_aliases=(("reanuda", 0.97), ("continua", 0.97), ("continuar", 0.96), ("resume", 0.96)),
    ),
    IntentSpec(
        "next_track",
        tool_handler="youtube_music.next",
        voice_aliases=(
            ("siguiente", 0.98),
            ("siguiente cancion", 0.98),
            ("proxima", 0.96),
            ("proxima cancion", 0.97),
            ("cancion siguiente", 0.96),
            ("next", 0.96),
            ("esa no", 0.94),
            ("otra", 0.86),
        ),
    ),
    IntentSpec(
        "previous_track",
        tool_handler="youtube_music.previous",
        voice_aliases=(("anterior", 0.98), ("anterior cancion", 0.98), ("cancion anterior", 0.96), ("previous", 0.96)),
    ),
    IntentSpec(
        "restart_track",
        tool_handler="youtube_music.restart",
        voice_aliases=(("reinicia", 0.98), ("reiniciar", 0.97), ("reinicia la cancion", 0.96)),
    ),
    IntentSpec(
        "current_track",
        tool_handler="youtube_music.get_current_track",
        voice_aliases=(("que suena", 0.95), ("que esta sonando", 0.95)),
    ),
    IntentSpec("set_volume", optional_entities=("level", "direction")),
    IntentSpec("web_search", ("query",), tool_handler="web.search_google"),
    IntentSpec("web_open", ("target",), tool_handler="web.open"),
    IntentSpec("browser_click", ("target",), tool_handler="browser.smart_click"),
    IntentSpec("open_application", ("name",), tool_handler="system.open_app"),
    IntentSpec("close_application", ("name",), tool_handler="system.close_app"),
    IntentSpec("remember_information", ("text",), tool_handler="memory.remember"),
    IntentSpec("get_time"),
    IntentSpec("get_date"),
    IntentSpec("assistant_status"),
    IntentSpec("rest"),
    IntentSpec("shutdown"),
    IntentSpec("unknown"),
)

INCOMPLETE_COMMANDS = {
    "pon",
    "ponme",
    "reproduce",
    "reproducir",
    "toca",
    "busca",
    "buscar",
    "quiero escuchar",
    "abre",
    "abrir",
}

REPEATABLE_NOISE = {
    "pon",
    "ponme",
    "busca",
    "buscar",
    "abre",
    "abrir",
    "eh",
    "ehh",
    "este",
}

CONVERSATION_CHECKS = {
    "me escuchas",
    "me oyes",
    "estas ahi",
    "estas ahí",
    "escuchas",
    "escuchame",
    "escucharme",
    "escucharse",
    "como te sientes",
    "como estas",
    "que tal estas",
}

COMMON_BROWSER_BUTTONS = {
    "aceptar",
    "cancelar",
    "continuar",
    "enviar",
    "guardar",
    "publicar",
    "confirmar",
}

CODEX_PREFIXES = (
    "dale ",
    "haz ",
    "dime ",
    "define ",
    "defineme ",
    "explica ",
    "explicame ",
    "revisa ",
    "consulta ",
)
