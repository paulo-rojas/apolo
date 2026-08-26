from typing import Any, Dict, Optional

from core.audio_gate import computer_audio_guard_active
from core.config import get_float, get_int
from core.logging import write_log
from .command_router import route_command
from .session import VoiceSession
from .wake_word import likely_wake_attempt, strip_wake_word


class VoiceGateway:
    def __init__(self, state: Optional[Any] = None):
        self.state = state
        self.session = VoiceSession(state)

    def handle_transcript(
        self,
        transcript: str,
        confidence: Optional[float] = None,
        duration_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not self._is_safe_input(transcript, confidence, duration_ms):
            return self._record("ignore", transcript, reason="unsafe or empty input")

        wake = strip_wake_word(transcript)
        session = self.session.get()
        if wake.detected:
            self.session.activate()
            if not wake.command:
                return self._record(
                    "session",
                    transcript,
                    command="",
                    reason="wake word recognized",
                    feedback="wake",
                )
            command = wake.command
        elif session["active"]:
            if computer_audio_guard_active():
                return self._record("ignore", transcript, reason="computer audio guard active")
            command = transcript
            self.session.touch()
        else:
            if likely_wake_attempt(transcript):
                return self._record("repeat", transcript, reason="wake word unclear", feedback="repeat")
            return self._record("ignore", transcript, reason="wake word not detected")

        routed = route_command(command, state=self.state)
        if routed.kind == "ignore" and wake.detected:
            if wake.matched in {"por lo", "hola por lo"}:
                return self._record(
                    "repeat",
                    transcript,
                    command=command,
                    reason="wake word unclear",
                    feedback="repeat",
                )
            if _should_repeat_unclear_wake_command(command):
                return self._record(
                    "repeat",
                    transcript,
                    command=command,
                    reason="command not understood",
                    feedback="repeat",
                )
            return self._record(
                "codex",
                transcript,
                command=command,
                reason="local parser did not understand command",
                feedback="processing",
            )
        if routed.kind != "ignore":
            self.session.touch()
        return self._record(
            routed.kind,
            transcript,
            command=routed.command,
            tool=routed.tool,
            args=routed.args or {},
            reason=routed.reason,
            interpretation=routed.interpretation.as_dict() if routed.interpretation else None,
            feedback=_feedback_for_route(routed.kind),
        )

    def _is_safe_input(
        self,
        transcript: str,
        confidence: Optional[float],
        duration_ms: Optional[int],
    ) -> bool:
        if not transcript or not transcript.strip():
            return False
        min_confidence = get_float("voice.min_confidence", 0.45, minimum=0.0)
        min_duration_ms = get_int("voice.min_duration_ms", 250, minimum=0)
        if confidence is not None and confidence < min_confidence:
            return False
        if duration_ms is not None and duration_ms < min_duration_ms:
            return False
        return True

    def _record(self, kind: str, transcript: str, **extra) -> Dict[str, Any]:
        result = {"ok": True, "kind": kind, "transcript": transcript, **extra}
        interpretation = extra.get("interpretation")
        write_log(
            "VOICE_NLU",
            "route",
            raw_text=_clip(transcript),
            normalized_text=_clip((interpretation or {}).get("normalized_text") or extra.get("command") or ""),
            selected_intent=(interpretation or {}).get("intent"),
            confidence=(interpretation or {}).get("confidence"),
            resolution_source=(interpretation or {}).get("source"),
            selected_tool=extra.get("tool"),
            route_kind=kind,
            reason=extra.get("reason"),
        )
        if self.state:
            self.state.set("lastTranscript", transcript)
            self.state.set("lastCommand", extra.get("command"))
            self.state.set("voiceSession", self.session.get())
        return result


def _feedback_for_route(kind: str) -> str:
    if kind == "mcp":
        return "complete"
    if kind == "codex":
        return "processing"
    if kind == "status":
        return "answer"
    if kind == "local":
        return "answer"
    if kind == "repeat":
        return "repeat"
    return "none"


def _clip(value: str, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _should_repeat_unclear_wake_command(command: str) -> bool:
    normalized = " ".join(str(command or "").lower().split())
    tokens = normalized.split()
    if not tokens:
        return False
    if len(tokens) <= 2:
        return True
    noise_tokens = {"ble", "alble", "pumbly"}
    return len(tokens) <= 3 and bool(set(tokens) & noise_tokens)
