import os
import subprocess
from pathlib import Path
from typing import Optional

from core.config import get_int, get_str


class WhisperCppNotConfigured(RuntimeError):
    pass


class WhisperCppTimeout(WhisperCppNotConfigured):
    pass


def whisper_model_name() -> str:
    model = (get_str("whisper.model", "small", env="APOLO_WHISPER_MODEL") or "small").lower()
    allowed = {"tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo"}
    if model not in allowed:
        raise ValueError(
            "APOLO_WHISPER_MODEL must be one of: tiny, base, small, medium, "
            "large-v2, large-v3, large-v3-turbo"
        )
    return model


def whisper_model_path() -> Path:
    explicit = get_str("whisper.model_path", env="APOLO_WHISPER_MODEL_PATH")
    if explicit:
        return Path(os.path.expandvars(explicit))
    return Path("models") / f"ggml-{whisper_model_name()}.bin"


def whisper_prompt() -> Optional[str]:
    return get_str("whisper.prompt", env="APOLO_WHISPER_PROMPT")


class WhisperCppTranscriber:
    def __init__(self, executable: Optional[str] = None, model_path: Optional[str] = None):
        configured_executable = get_str("whisper.executable", env="APOLO_WHISPER_CPP_EXE")
        self.executable = Path(os.path.expandvars(executable or configured_executable or ""))
        self.model_path = Path(os.path.expandvars(model_path)) if model_path else whisper_model_path()

    def transcribe_file(self, wav_path: str, language: str = "es") -> str:
        if not self.executable.is_file():
            raise WhisperCppNotConfigured("APOLO_WHISPER_CPP_EXE must point to whisper.cpp executable")
        if not self.model_path.is_file():
            raise WhisperCppNotConfigured(f"whisper.cpp model not found: {self.model_path}")

        output_base = Path(wav_path).with_suffix(".whisper")
        cmd = [
            str(self.executable),
            "-m",
            str(self.model_path),
            "-f",
            str(wav_path),
            "-l",
            language,
            "-nt",
            "-t",
            str(get_int("whisper.threads", 8, env="APOLO_WHISPER_THREADS", minimum=1)),
            "-otxt",
            "-of",
            str(output_base),
        ]
        prompt = whisper_prompt()
        if prompt:
            cmd.extend(["--prompt", prompt])
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            cmd,
            startupinfo=startupinfo,
            creationflags=creationflags,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=get_int("whisper.timeout_seconds", 120, env="APOLO_WHISPER_TIMEOUT_SECONDS", minimum=5),
            check=True,
        )
        transcript_path = Path(f"{output_base}.txt")
        try:
            if transcript_path.is_file():
                return _extract_transcript(transcript_path.read_text(encoding="utf-8", errors="replace"))
            return _extract_transcript(result.stdout or "")
        finally:
            transcript_path.unlink(missing_ok=True)


def _extract_transcript(output: str) -> str:
    lines = []
    for line in output.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if clean.startswith("[") and "]" in clean:
            clean = clean.split("]", 1)[1].strip()
        lines.append(clean)
    return " ".join(lines).strip()
