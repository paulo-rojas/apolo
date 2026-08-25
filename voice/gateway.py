from typing import Any, Dict, Optional

from core.config import get_float, get_int
from .command_router import route_command
from .session import VoiceSession
from .wake_word import strip_wake_word


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
            command = transcript
            self.session.touch()
        else:
            return self._record("ignore", transcript, reason="wake word not detected")

        routed = route_command(command)
        if routed.kind != "ignore":
            self.session.touch()
        return self._record(
            routed.kind,
            transcript,
            command=routed.command,
            tool=routed.tool,
            args=routed.args or {},
            reason=routed.reason,
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
    return "none"
