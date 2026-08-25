import time
from typing import Any, Dict, Optional

from core.config import get_int


DEFAULT_SESSION = {"active": False, "lastActivity": None}


def voice_session_timeout_seconds() -> int:
    return get_int(
        "voice.session_timeout_seconds",
        20,
        env="APOLO_VOICE_SESSION_TIMEOUT_SECONDS",
        minimum=1,
    )


class VoiceSession:
    def __init__(self, state: Optional[Any] = None):
        self.state = state

    def get(self) -> Dict[str, Any]:
        session = self.state.get("voiceSession", DEFAULT_SESSION) if self.state else DEFAULT_SESSION
        last_activity = session.get("lastActivity")
        active = bool(session.get("active"))
        if active and last_activity:
            active = (time.time() - float(last_activity)) <= voice_session_timeout_seconds()
        return {"active": active, "lastActivity": last_activity if active else None}

    def activate(self) -> Dict[str, Any]:
        session = {"active": True, "lastActivity": time.time()}
        if self.state:
            self.state.set("voiceSession", session)
        return session

    def touch(self) -> Dict[str, Any]:
        current = self.get()
        if not current["active"]:
            return current
        return self.activate()

    def deactivate(self) -> Dict[str, Any]:
        session = {"active": False, "lastActivity": None}
        if self.state:
            self.state.set("voiceSession", session)
        return session
